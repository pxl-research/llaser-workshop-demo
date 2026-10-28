import logging
from datetime import datetime

from AI.API import settings
from AI.Chunking.Vector_Stores import ChromaVectorStore

logger = logging.getLogger(__name__)


class SessionMemory:
    """The Q&A turns of one chat session, stored in Chroma."""

    def __init__(self, embedding_model, session_id: str = None):
        self.session_id = session_id
        self.vector_store = ChromaVectorStore(
            db_name="session_memory",
            embedding_model=embedding_model,
            persist_directory=str(settings.STORE_DIR / "session_memory_db"),
        )

    def store_conversation(self, question: str, answer: str) -> None:
        """Store a Q&A pair in the vector store."""
        if not self.session_id:
            return

        conversation_text = f"Q: {question}\nA: {answer}"
        timestamp = datetime.now().isoformat()
        doc_id = f"{self.session_id}_{timestamp.replace(':', '-').replace('.', '_')}"

        try:
            self.vector_store.collection.add(
                documents=[conversation_text],
                metadatas=[{
                    "session_id": self.session_id,
                    "timestamp": timestamp,
                    "question": question,
                    "answer": answer,
                    "doc_id": doc_id
                }],
                ids=[doc_id]
            )
        except Exception:
            logger.exception("Storing conversation in memory failed")

    def get_recent_turns(self, n: int) -> list[dict]:
        """The newest n Q&A pairs of this session, oldest first, as {question, answer, doc_id}."""
        if not self.session_id:
            return []
        try:
            results = self.vector_store.collection.get(where={"session_id": self.session_id}, include=["metadatas"])
        except Exception:
            logger.exception("Retrieving recent turns failed; answering without history")
            return []
        rows = sorted(results.get("metadatas") or [], key=lambda m: (m or {}).get("timestamp", ""))
        return [{key: (m or {}).get(key, "") for key in ("question", "answer", "doc_id")} for m in rows[-n:]]

    def retrieve_context(self, question: str, k: int = 5, min_similarity: float = 0.3, exclude_ids=()) -> str:
        """
        Past conversations of this session related to the question, formatted for the prompt.

        min_similarity: minimum score (1 - squared L2 distance). For unit-length embeddings
        score = 2 * cosine - 1, so 0.3 means cosine >= 0.65 and the 0.67 callers pass means cosine >= 0.835.
        """
        if not self.session_id:
            return ""

        try:
            results = self.vector_store.collection.query(
                query_texts=[question],
                n_results=k + len(exclude_ids),
                where={"session_id": self.session_id},
                include=['documents', 'metadatas', 'distances']
            )

            if not results or not results['documents'] or not results['documents'][0]:
                return ""

            context_parts = []
            # Chroma's default space is squared L2 (lower = more similar); 1 - distance is a score, not cosine.
            for doc, metadata, distance in zip(results['documents'][0], results['metadatas'][0], results['distances'][0]):
                if (metadata or {}).get("doc_id") in exclude_ids or len(context_parts) == k:
                    continue
                similarity = 1 - distance
                if similarity >= min_similarity:
                    context_parts.append(f"[Past Interaction at {metadata.get('timestamp', 'N/A')} | Similarity: {similarity:.2f}]\n{doc}")

            return "\n\n".join(context_parts)

        except Exception:
            logger.exception("Retrieving related conversations failed")
            return ""
