import logging
from pathlib import Path

import pymupdf4llm

from AI.API import settings
from AI.API.exceptions import DocumentProcessingError
from AI.API.LLM import stream_text
from AI.API.SessionMemory import SessionMemory
from AI.Chunking.OpenAI_Embedding import OpenAIEmbeddingModel
from AI.Chunking.Reranker import OpenRouterReranker
from AI.Chunking.Splitter import MarkdownSplitter
from AI.Chunking.Vector_Stores import ChromaVectorStore, compute_hash

logger = logging.getLogger(__name__)

MAX_CHUNK_SIZE = 2000


def load_pdf(file_path: str) -> list[str]:
    """The PDF as one Markdown text; tables stay Markdown tables."""
    return [pymupdf4llm.to_markdown(file_path)]


class RAG:
    def __init__(self, on_progress=None):
        self._report_progress(on_progress, "embedding", "loading", settings.EMBEDDING_MODEL)
        self.embedder = OpenAIEmbeddingModel(settings.EMBEDDING_MODEL)
        self._report_progress(on_progress, "embedding", "ready", settings.EMBEDDING_MODEL)

        self._report_progress(on_progress, "reranker", "loading", settings.RERANKER)
        self.reranker = OpenRouterReranker(model_id=settings.RERANKER)
        self._report_progress(on_progress, "reranker", "ready", settings.RERANKER)

        self._report_progress(on_progress, "vector_store", "loading")
        self.vector_store = ChromaVectorStore(
            db_name="documents",
            embedding_model=self.embedder,
            persist_directory=str(settings.STORE_DIR / "chroma_db_data"),
        )
        self._index_existing_files()
        self._report_progress(on_progress, "vector_store", "ready")

        self._session_memories = {}

        self._report_progress(on_progress, "llm", "ready", settings.LLM)

    @staticmethod
    def _report_progress(on_progress, component: str, state: str, model: str | None = None):
        if on_progress is not None:
            on_progress(component, state, model)

    def _index_existing_files(self) -> None:
        """Index files left on disk from an earlier run, and drop chunks of files that are gone."""
        splitter = MarkdownSplitter(max_chunk_size=MAX_CHUNK_SIZE)
        self._prune_to_disk()
        for file_path in self._source_files():
            try:
                if self.vector_store.is_indexed(str(file_path)):
                    continue
                texts = load_pdf(str(file_path))
                if not texts:
                    continue
                self.vector_store.add_document(str(file_path), splitter.split(texts))
            except Exception:
                logger.exception("Startup indexing failed for %s", file_path.name)

    def _source_files(self) -> list[Path]:
        """Documents under UPLOAD_DIR, never the store."""
        # STORE_DIR (Chroma files) lives inside UPLOAD_DIR.
        store_dir = settings.STORE_DIR.resolve()
        return [p for p in settings.UPLOAD_DIR.rglob("*")
                if p.is_file() and p.suffix.lower() in settings.DOCUMENT_EXTENSIONS
                and store_dir not in p.resolve().parents]

    def _prune_to_disk(self) -> None:
        if not settings.UPLOAD_DIR.is_dir():
            # An unmounted source dir is not an empty corpus; pruning would wipe the index.
            logger.warning("Source dir missing, stale chunks kept: %s", settings.UPLOAD_DIR)
            return
        try:
            # Content hash is the identity: drop chunks whose file is gone or changed.
            self.vector_store.prune_missing({h for h in (compute_hash(str(p)) for p in self._source_files()) if h})
        except Exception:
            logger.exception("Pruning stale chunks failed; stale content kept")

    def stream_query(self, question: str, session_id: str = None):
        """Yield answer text pieces; return the usage dict once the answer is stored."""
        if session_id not in self._session_memories:
            self._session_memories[session_id] = SessionMemory(self.embedder, session_id=session_id)
        session_mem = self._session_memories[session_id]

        # 0) The newest turns go to the model as real chat history; older ones only when related
        recent = session_mem.get_recent_turns(settings.CHAT_HISTORY_TURNS)
        history = [(turn["question"], turn["answer"]) for turn in recent]
        conversation_history = session_mem.retrieve_context(
            question, k=3, min_similarity=0.67, exclude_ids={turn["doc_id"] for turn in recent}
        )

        # 1) retrieve more than you want, then rerank. A follow-up ("and who teaches it?") names no topic,
        # so the search also gets the previous question; the reranker then judges against the new one.
        search_query = f"{history[-1][0]}\n{question}" if history else question
        retrieved_chunks = self.vector_store.retrieve_top_chunks(search_query, k=10)

        # 2) rerank chunks with cross-encoder
        reranked_chunks = self.reranker.rerank(question, retrieved_chunks, top_n=3)

        # 3) build context from reranked chunks and conversation history
        context = "\n".join(reranked_chunks)
        if conversation_history:
            context = f"Related past conversations:\n{conversation_history}\n\nCurrent context:\n{context}"

        # str.replace, not format: attendees edit this prompt, and braces in it must stay literal.
        system_prompt = settings.SYSTEM_PROMPT.replace("{context}", context)

        usage, answer = yield from stream_text(
            model=settings.LLM,
            system_prompt=system_prompt,
            user_message=question,
            history=history,
            max_new_tokens=settings.RAG_MAX_OUTPUT_TOKENS,
        )

        logger.debug("LLM answer: %s", answer)
        session_mem.store_conversation(question, answer)
        return usage

    def process_and_add_document(self, file_path: str) -> dict:
        """Index one document; the result carries only a curated error message."""
        failure = DocumentProcessingError.GENERIC
        try:
            file_path_obj = Path(file_path)
            if not file_path_obj.exists():
                logger.error("Document to process not found: %s", file_path_obj.name)
                return self._document_error(DocumentProcessingError.UNREADABLE)

            if self.vector_store.is_indexed(str(file_path)):
                self._prune_to_disk()
                return {"status": "success", "message": "Document already indexed",
                        "file": file_path, "chunks": 0, "already_indexed": True}

            failure = DocumentProcessingError.UNREADABLE
            texts = load_pdf(str(file_path))
            if not texts:
                logger.error("Document is empty or could not be loaded: %s", file_path_obj.name)
                return self._document_error(DocumentProcessingError.UNREADABLE)

            failure = DocumentProcessingError.SPLIT_FAILED
            chunks = MarkdownSplitter(max_chunk_size=MAX_CHUNK_SIZE).split(texts)
            if not chunks:
                logger.error("Document produced no chunks: %s", file_path_obj.name)
                return self._document_error(DocumentProcessingError.SPLIT_FAILED)

            failure = DocumentProcessingError.INDEX_FAILED
            added_chunks = self.vector_store.add_document(str(file_path), chunks)
            # A re-upload replaced the file on disk; drop the old version's chunks.
            # ponytail: rehashes every source file per upload; cache path->hash if uploads get slow.
            self._prune_to_disk()

            return {
                "status": "success",
                "message": "Document processed and added successfully",
                "file": file_path,
                "chunks": added_chunks,
                "already_indexed": added_chunks == 0,
            }

        except Exception:
            logger.exception("Error processing document %s", Path(file_path).name)
            return self._document_error(failure)

    def delete_document(self, file_path: str) -> None:
        """Remove a document from disk and drop its chunks."""
        Path(file_path).unlink(missing_ok=True)
        self._prune_to_disk()

    @staticmethod
    def _document_error(user_message: str) -> dict:
        """Error result carrying only a curated message, never raw exception text."""
        return {"status": "error", "message": user_message}
