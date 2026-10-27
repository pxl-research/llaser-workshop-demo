#!/usr/bin/env python3

import logging
import os
from datetime import datetime
from AI.API import settings
from AI.API.embeddings import DEFAULT_EMBEDDING_MODEL
from AI.Chunking.Vector_Stores import ChromaVectorStore, collection_name, drop_legacy_collections
from AI.Chunking.Embedding_Provider import BaseEmbeddingModel

logger = logging.getLogger(__name__)


class SessionMemory:
    """Manages conversation history using decoupled query retrieval for better semantic matching."""

    def __init__(self, embedding_model: BaseEmbeddingModel, session_id: str = None, model_name: str = None):
        """
        Initialize SessionMemory.

        Args:
            embedding_model: BaseEmbeddingModel instance for embedding conversations
            session_id: Unique identifier for the session.
            model_name: Name of the embedding model (e.g. "baai/bge-m3"). It selects the
                        per-model collection. Defaults to the EMBEDDING_MODEL env var.
        """
        self.embedding_model = embedding_model
        self.session_id = session_id
        model_name = model_name or os.getenv("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
        self.vector_store = ChromaVectorStore(
            db_name=collection_name("session_memory", model_name),
            embedding_model=embedding_model,
            persist_directory=str(settings.STORE_DIR / "session_memory_db")
        )
        self.vector_store.connect()
        self.vector_store.create()
        try:
            drop_legacy_collections(self.vector_store.client)
        except Exception:
            logger.exception("Legacy session memory cleanup failed; legacy collections kept")

    def switch_embedding_model(self, embedding_model: BaseEmbeddingModel, model_name: str) -> None:
        """Point this memory at the collection of another embedding model, keeping the old one intact."""
        self.embedding_model = embedding_model
        self.vector_store.use_collection(collection_name("session_memory", model_name), embedding_model)

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
        except Exception as e:
            print(f"Error storing conversation in memory: {e}")
    
    def retrieve_context(self, raw_question: str, optimized_search_query: str = None, k: int = 5, min_similarity: float = 0.3) -> str:
        """
        Retrieve relevant past conversations.
        
        Args:
            raw_question: The literal question the user just asked.
            optimized_search_query: An LLM-rewritten, highly descriptive version of the question. 
                                    If provided, this is what actually gets embedded and searched.
            k: Number of past conversations to retrieve.
            min_similarity: Minimum score (1 - squared L2 distance) to include results. Higher = stricter filtering.
                           For unit-length embeddings score = 2 * cosine - 1, so 0.3 means cosine >= 0.65
                           and the 0.67 callers pass means cosine >= 0.835.
            
        Returns:
            Formatted string of relevant past conversations.
        """
        if not self.session_id:
            return ""
            
        # Use the optimized query if provided; otherwise fallback to the raw question
        search_target = optimized_search_query if optimized_search_query else raw_question
        
        try:
            results = self.vector_store.collection.query(
                query_texts=[search_target],
                n_results=k,
                where={"session_id": self.session_id},
                include=['documents', 'metadatas', 'distances']
            )
            
            if not results or not results['documents'] or not results['documents'][0]:
                return ""
            
            context_parts = []
            # Chroma's default space is squared L2 (lower = more similar); 1 - distance is a score, not cosine.
            for doc, metadata, distance in zip(results['documents'][0], results['metadatas'][0], results['distances'][0]):
                similarity = 1 - distance
                if similarity >= min_similarity:  # Only include if meets minimum similarity threshold
                    context_parts.append(f"[Past Interaction at {metadata.get('timestamp', 'N/A')} | Similarity: {similarity:.2f}]\n{doc}")
            
            if context_parts:
                return "\n\n".join(context_parts)
            return ""
            
        except Exception as e:
            print(f"Error retrieving context: {e}")
            return ""

    def get_most_recent_message(self) -> str:
        """
        Retrieve the most recent conversation message.
        
        Returns:
            Formatted string of the most recent conversation, or empty string if none exist.
        """
        if not self.session_id:
            return ""
        
        try:
            results = self.vector_store.collection.get(
                where={"session_id": self.session_id}, include=["documents", "metadatas"]
            )
            pairs = list(zip(results.get("documents") or [], results.get("metadatas") or []))
            if not pairs:
                return ""
            doc, metadata = max(pairs, key=lambda p: (p[1] or {}).get("timestamp", ""))
            return f"[Previous Interaction at {metadata.get('timestamp', 'N/A')}]\n{doc}"

        except Exception as e:
            print(f"Error retrieving most recent message: {e}")
            return ""

    def clear_session(self) -> None:
        """Deletes all memory associated with the current session_id."""
        if not self.session_id:
            return
        try:
            self.vector_store.collection.delete(where={"session_id": self.session_id})
        except Exception as e:
            print(f"Error clearing session memory: {e}")

    def close(self) -> None:
        """Close the vector store connection."""
        self.vector_store.close()