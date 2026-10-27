#!/usr/bin/env python3

import logging
from pathlib import Path
import os
import sys
import types

from AI.Chunking.Splitter import TokenBasedSplitter

from AI.Chunking.PyMuPDF4LLM_Loader import PyMuPDF4LLMLoader
from AI.Chunking.AzureDocument_Loader import AzureDocumentIntelligenceLoader
from AI.Chunking.LlamaParse_Loader import LlamaParseLoader

from .LLM import LLM
from AI.API import settings
from AI.API.exceptions import DocumentProcessingError
from AI.API.embeddings import DEFAULT_EMBEDDING_MODEL, create_embedding_model
from AI.Chunking.Vector_Stores import (
    ChromaVectorStore,
    collection_name,
    compute_hash,
    copy_missing_chunks,
    drop_legacy_collections,
    migrate_legacy_collection,
)
from dotenv import load_dotenv
from AI.Chunking.Splitter import TokenBasedSplitter, MarkdownSplitter
from AI.API.rerankers import DEFAULT_RERANKER, create_reranker_model
from .SessionMemory import SessionMemory

logger = logging.getLogger(__name__)

try:
    from AI.API.RAG_Helpers import download_container_documents
except:
    print("RAG_Helpers not imported, assuming local deployment without document downloading.")

script_dir = os.path.dirname(os.path.abspath(__file__))
    
sys.modules['frontend'] = types.SimpleNamespace(
    __file__='.',
    server=types.SimpleNamespace(
        app=types.SimpleNamespace(
            mount=lambda *a, **k: None
        )
    )
)

def create_document_loader(name: str):
    name = name or settings.DEFAULT_DOCUMENT_LOADER
    factories = {
        "llama_parse": lambda: LlamaParseLoader(),
        "azure_document_intelligence": lambda: AzureDocumentIntelligenceLoader(),
        "pymupdf4llm": lambda: PyMuPDF4LLMLoader(),
      
    }

    factory = factories.get(name)
    if factory is None:
        raise ValueError(f"Unknown DOCUMENT_LOADER value: {name}")

    return factory()


class RAG:
    def __init__(self, session_id: str = None, on_progress=None):
        load_dotenv()

        embedder_name = os.getenv("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
        reranker_name = os.getenv("RERANKER") or DEFAULT_RERANKER

        self._report_progress(on_progress, "embedding", "loading", embedder_name)
        self.embedder = create_embedding_model(embedder_name)
        self._report_progress(on_progress, "embedding", "ready", embedder_name)
        self.current_embedding_model = embedder_name

        self._report_progress(on_progress, "reranker", "loading", reranker_name)
        self.reranker = create_reranker_model(reranker_name)
        self._report_progress(on_progress, "reranker", "ready", reranker_name)

        self._report_progress(on_progress, "vector_store", "loading")
        self.vector_store = self._setup_vector_store()
        self._report_progress(on_progress, "vector_store", "ready")

        self.session_memory = SessionMemory(
            self.embedder, session_id=session_id, model_name=self.current_embedding_model
        )

        llm_name = os.environ.get("LLM")
        self._report_progress(on_progress, "llm", "loading", llm_name)
        self.llm = LLM(llm_name)
        self._report_progress(on_progress, "llm", "ready", llm_name)

        # Store current configuration names
        self.current_reranker_model = reranker_name
        self.current_llm = llm_name

    @staticmethod
    def _report_progress(
        on_progress,
        component: str,
        state: str,
        model: str | None = None,
        message: str | None = None,
    ):
        if on_progress is None:
            return
        on_progress(component, state, model, message)
        
    def get_current_embedding_model(self):
        return self.current_embedding_model

    def get_current_reranker_model(self):
        return self.current_reranker_model

    def get_current_llm(self):
        return self.current_llm
    
    def _setup_vector_store(self):
        ai_name = os.getenv("AI_NAME")
        deployement = os.getenv("DEPLOYMENT_ENV")
        if (deployement == "local"):
            data_path = settings.UPLOAD_DIR
        else:
            data_path_str = download_container_documents(ai_name)
            data_path = Path(data_path_str)

        splitter = MarkdownSplitter(max_chunk_size=2000)

        store = ChromaVectorStore(
            db_name=collection_name("rag", self.current_embedding_model),
            embedding_model=self.embedder,
            persist_directory=str(settings.STORE_DIR / "chroma_db_data"),
        )
        store.connect()
        store.create()
        try:
            migrate_legacy_collection(store, "rag", self.current_embedding_model)
            drop_legacy_collections(store.client)
        except Exception:
            logger.exception("Legacy collection migration failed; legacy collections kept")
        self._data_path = data_path
        self.vector_store = store
        sources = self._source_files()
        self._prune_to_disk()
        loader = None
        for file_path in sources:
            try:
                if store.is_indexed(str(file_path)):
                    continue
                # Created on first need: missing loader keys must not block startup when everything is indexed.
                loader = loader or create_document_loader(os.getenv("DOCUMENT_LOADER"))
                texts = loader.load_document(str(file_path))
                if not texts:
                    continue
                chunks = splitter.split(texts)
                store.add_document(str(file_path), chunks)
            except Exception:
                logger.exception("Startup indexing failed for %s", file_path.name)
                continue

        return store

    def _source_roots(self) -> list[Path]:
        # Local data_path is UPLOAD_DIR itself, so dedupe roots.
        return list(dict.fromkeys((self._data_path, settings.UPLOAD_DIR)))

    def _source_files(self) -> list[Path]:
        """Files the active loader can read under the data path and UPLOAD_DIR, never the store."""
        # STORE_DIR (Chroma files) lives inside UPLOAD_DIR.
        store_dir = settings.STORE_DIR.resolve()
        allowed = settings.allowed_document_extensions()
        return [p for root in self._source_roots() for p in root.rglob("*")
                if p.is_file() and p.suffix.lower() in allowed and store_dir not in p.resolve().parents]

    def _prune_to_disk(self) -> None:
        missing = [root for root in self._source_roots() if not root.is_dir()]
        if missing:
            # An unmounted source dir is not an empty corpus; pruning would wipe the index.
            logger.warning("Source dir missing, stale chunks kept: %s", ", ".join(map(str, missing)))
            return
        try:
            # Content hash is the identity: drop chunks whose file is gone or changed (uploads share this collection).
            self.vector_store.prune_missing({h for h in (compute_hash(str(p)) for p in self._source_files()) if h})
        except Exception:
            logger.exception("Pruning stale chunks failed; stale content kept")

    def stream_query(self, question: str, session_id: str = None):
        """Yield answer text pieces; return the usage dict once the answer is stored."""
        # Use provided session_id or create temporary session memory
        if session_id:
            # Create or reuse session memory for this session
            if not hasattr(self, '_session_memories'):
                self._session_memories = {}
            
            if session_id not in self._session_memories:
                self._session_memories[session_id] = SessionMemory(
                    self.embedder, session_id=session_id, model_name=self.current_embedding_model
                )
            
            session_mem = self._session_memories[session_id]
        else:
            session_mem = self.session_memory
        
        # 0) Retrieve relevant past conversations and most recent message for context
        most_recent = session_mem.get_most_recent_message()
        conversation_history = session_mem.retrieve_context(question, k=3, min_similarity=0.67)
        
        # 1) retrieve more than you want, then rerank
        retrieved_chunks = self.vector_store.retrieve_top_chunks(question, k=10)

        # 2) rerank chunks with cross-encoder
        if retrieved_chunks:
            reranked_chunks = self.reranker.rerank(
                question, retrieved_chunks, top_n=3
            )
        else:
            reranked_chunks = []

        # 3) build context from reranked chunks and conversation history
        context = "\n".join(reranked_chunks)
        
        # Add most recent message if available
        if most_recent:
            context = f"Most recent context:\n{most_recent}\n\nDocument context:\n{context}"
        
        # Add other conversation history if available
        if conversation_history:
            context = f"Related past conversations:\n{conversation_history}\n\nCurrent context:\n{context}"
        
        # str.replace, not format: attendees edit this prompt, and braces in it must stay literal.
        system_prompt = settings.SYSTEM_PROMPT.replace("{context}", context)
        user_message = question

        usage, answer = yield from self.llm.stream_text(
            system_prompt=system_prompt,
            user_message=user_message,
            max_new_tokens=settings.RAG_MAX_OUTPUT_TOKENS,
            temperature=0.0,
        )

        logger.debug("LLM answer: %s", answer)
        # Store this conversation in memory for future reference
        session_mem.store_conversation(question, answer)
        return usage

    def update_llm(self, llm_name: str) -> dict:
        """
        Update the LLM model.
        
        Args:
            llm_name: Name of the new LLM model
            
        Returns:
            dict with status and message
        """
        try:
            self.llm = LLM(llm_name)
            self.current_llm = llm_name
            os.environ["LLM"] = llm_name
            return {
                "status": "success",
                "message": f"LLM updated to {llm_name}",
                "model": llm_name
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to update LLM: {str(e)}",
                "model": None
            }

    def update_embedding_model(self, embedding_name: str, update_reranker: bool = True) -> dict:
        """
        Update the embedding model and optionally the reranker.
        Switches to the new model's own collections; the old model's collections are kept.
        The new document collection is topped up from the old one before it becomes active.
        
        Args:
            embedding_name: Name of the new embedding model
            update_reranker: Whether to also update the reranker (default True)
            
        Returns:
            dict with status and message
        """
        try:
            # Create everything that can fail before mutating any state
            new_embedder = create_embedding_model(embedding_name)
            reranker_name = os.getenv("RERANKER") or DEFAULT_RERANKER
            new_reranker = create_reranker_model(reranker_name) if update_reranker else self.reranker
            new_collection = collection_name("rag", embedding_name)

            # Each embedding model has its own collections; the old ones stay untouched.
            # Fill the new one before it goes live: a failed copy keeps the old model active and complete,
            # and a retry resumes from it.
            target = self.vector_store.get_collection(new_collection, new_embedder)
            re_embed_result = self.re_embed_all_documents(self.vector_store.collection, target)
            if re_embed_result.get("status") == "error":
                return {
                    "status": "error",
                    "message": f"Embedding model not changed: {re_embed_result['message']}",
                    "embedding_model": None,
                    "reranker_updated": False,
                    "documents_reembedded": 0,
                    "chunks_reembedded": 0
                }

            self.vector_store.use_collection(new_collection, new_embedder)

            self.session_memory.switch_embedding_model(new_embedder, embedding_name)
            if hasattr(self, '_session_memories'):
                for mem in self._session_memories.values():
                    mem.switch_embedding_model(new_embedder, embedding_name)

            # Update the main embedder
            self.embedder = new_embedder
            self.current_embedding_model = embedding_name
            os.environ["EMBEDDING_MODEL"] = embedding_name

            self.reranker = new_reranker

            # Copying can bring back chunks of files deleted since; the active collection must match disk.
            self._prune_to_disk()

            return {
                "status": "success",
                "message": f"Embedding model updated to {embedding_name}. {re_embed_result['message']}",
                "embedding_model": embedding_name,
                "reranker_updated": update_reranker,
                "documents_reembedded": re_embed_result.get("documents_processed", 0),
                "chunks_reembedded": re_embed_result.get("chunks", 0)
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to update embedding model: {str(e)}",
                "embedding_model": None,
                "reranker_updated": False
            }

    def update_reranker(self, reranker_name: str) -> dict:
        """
        Update the reranker model.
        
        Args:
            reranker_name: Name of the new reranker model
            
        Returns:
            dict with status and message
        """
        try:
            self.reranker = create_reranker_model(reranker_name)
            self.current_reranker_model = reranker_name
            os.environ["RERANKER"] = reranker_name
            return {
                "status": "success",
                "message": f"Reranker updated to {reranker_name}",
                "model": reranker_name
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to update reranker: {str(e)}",
                "model": None
            }

    def get_current_config(self) -> dict:
        """
        Get the current model configuration.
        
        Returns:
            dict with current LLM, embedding, and reranker models
        """
        return {
            "llm": self.current_llm,
            "embedding_model": self.current_embedding_model,
            "reranker": self.current_reranker_model
        }

    def process_and_add_document(self, file_path: str) -> dict:
        """
        Process a single document and add it to the vector store.
        
        Args:
            file_path: Path to the document file
            
        Returns:
            dict with status and message
        """
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

            # Create document loader and splitter
            loader = create_document_loader(os.getenv("DOCUMENT_LOADER"))
            splitter = MarkdownSplitter(max_chunk_size=2000)

            # Load document
            failure = DocumentProcessingError.UNREADABLE
            texts = loader.load_document(str(file_path))
            if not texts:
                logger.error("Document is empty or could not be loaded: %s", file_path_obj.name)
                return self._document_error(DocumentProcessingError.UNREADABLE)

            # Split into chunks
            failure = DocumentProcessingError.SPLIT_FAILED
            chunks = splitter.split(texts)
            if not chunks:
                logger.error("Document produced no chunks: %s", file_path_obj.name)
                return self._document_error(DocumentProcessingError.SPLIT_FAILED)

            # Add to vector store
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

    @staticmethod
    def _document_error(user_message: str) -> dict:
        """Error result carrying only a curated message, never raw exception text."""
        return {"status": "error", "message": user_message}

    def re_embed_all_documents(self, source_collection, target_collection) -> dict:
        """
        Copy the documents of source_collection (the previous embedding model's
        collection) into target_collection, embedding them with the target's
        embedding model. The source collection is never reset or deleted.
        Only chunks missing from the target collection are copied.
        Chunks of files deleted from disk are copied too; update_embedding_model prunes them afterwards.

        Returns:
            dict with status, message, and number of documents re-embedded
        """
        try:
            if not source_collection:
                return {
                    "status": "success",
                    "message": "No documents to re-embed",
                    "documents_processed": 0
                }

            # Copied in batches; Chroma re-embeds them with the current embedding model
            try:
                copied = copy_missing_chunks(source_collection, target_collection)
            except Exception as e:
                logger.exception("Error re-adding documents: %s", e)
                return {
                    "status": "error",
                    "message": f"Failed to re-embed documents: {str(e)}",
                    "documents_processed": 0
                }

            if not copied:
                reused = target_collection.count() > 0
                return {
                    "status": "success",
                    "message": "Existing index for this embedding model reused" if reused else "No documents to re-embed",
                    "documents_processed": 0
                }

            logger.info("Re-embedded %d chunks with the new embedding model", copied)
            return {
                "status": "success",
                "message": "Successfully re-embedded all documents with new embedding model",
                "documents_processed": copied,
                "chunks": copied
            }

        except Exception as e:
            logger.exception("Error in re_embed_all_documents: %s", e)
            return {
                "status": "error",
                "message": f"Error re-embedding documents: {str(e)}",
                "documents_processed": 0
            }


if __name__ == "__main__":
    rag = RAG()
    print("".join(rag.stream_query("Summarize the contents of the local ./data folder.")))
