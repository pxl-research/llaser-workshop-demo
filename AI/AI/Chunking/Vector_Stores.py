import hashlib
import logging
import os
import re

import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)


def compute_hash(file_path: str) -> str:
    """SHA-256 of a file's content, or "" when the file does not exist."""
    if not os.path.exists(file_path):
        return ""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


KEYWORD_EXTRA = 5
_EXACT_TERM = re.compile(r'"([^"]+)"|(\b[\w.-]*\d[\w.-]*\b)|(\b[A-Z]{2,}\b)')


def exact_terms(question: str) -> list[str]:
    """Quoted phrases, digit-bearing tokens and ALL-CAPS acronyms: max 3, de-duplicated, in order."""
    # ponytail: Chroma $contains is case-sensitive and this heuristic is naive;
    # upgrade to a real BM25/full-text index if recall on exact terms is still poor.
    terms = []
    for match in _EXACT_TERM.finditer(question):
        term = (match.group(1) or match.group(2) or match.group(3)).rstrip(".-")
        # Short bare numbers ("step 2") match nearly every chunk
        if term and term not in terms and not (term.isdigit() and len(term) < 3):
            terms.append(term)
    return terms[:3]


class EmbeddingFunction(embedding_functions.EmbeddingFunction):
    """Adapts an embedding model to Chroma's embedding function API."""

    def __init__(self, embedding_model):
        self.embedding_model = embedding_model

    def __call__(self, texts):
        return self.embedding_model.embed_documents(texts)


class ChromaVectorStore:
    def __init__(self, db_name: str, embedding_model, persist_directory: str):
        self.db_name = db_name
        self.persist_directory = persist_directory
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection(
            name=db_name, embedding_function=EmbeddingFunction(embedding_model)
        )
        logger.info("Chroma Collection '%s' ready in %s", db_name, persist_directory)

    def is_indexed(self, file_path: str) -> bool:
        """True when a file with the same content hash is already in the collection."""
        file_hash = compute_hash(file_path)
        if not file_hash:
            return False
        return bool(self.collection.get(where={"file_hash": file_hash}, limit=1, include=[])["ids"])

    def prune_missing(self, keep_hashes: set[str]) -> None:
        """Delete chunks whose source content (file_hash) is no longer on disk; an empty set empties the collection."""
        if keep_hashes:
            self.collection.delete(where={"file_hash": {"$nin": sorted(keep_hashes)}})
            return
        # Chroma rejects an empty $nin
        ids = self.collection.get(include=[])["ids"]
        if ids:
            self.collection.delete(ids=ids)

    def add_document(self, file_path: str, chunks: list[str]) -> int:
        """
        Add a document's chunks; Chroma embeds and indexes them.

        Returns the number of chunks added, or 0 when nothing was added
        (empty input or the same file hash is already indexed).
        Raises RuntimeError when the collection insert fails.
        """
        if not file_path or not chunks:
            return 0

        file_hash = compute_hash(file_path)
        if self.collection.get(where={"file_hash": file_hash}, limit=1, include=[])["ids"]:
            logger.info("Document %s already indexed in the vector store", file_path)
            return 0

        # Content-addressed IDs: a changed file at the same path never collides with old chunks
        ids = [f"{file_hash}_{i}" for i in range(len(chunks))]
        metadatas = [
            {"file_path": file_path, "file_hash": file_hash, "chunk_index": i}
            for i in range(len(chunks))
        ]
        try:
            self.collection.add(documents=chunks, metadatas=metadatas, ids=ids)
        except Exception as exc:
            logger.exception("Error adding document %s to Chroma: %s", file_path, exc)
            raise RuntimeError(f"Failed to add document to Chroma: {exc}") from exc

        logger.info("Added %d chunks for document: %s", len(chunks), file_path)
        return len(chunks)

    def retrieve_top_chunks(self, question: str, k: int) -> list[str]:
        """Similarity search, plus up to KEYWORD_EXTRA exact-term (keyword) matches for the reranker."""
        results = self.collection.query(query_texts=[question], n_results=k, include=["documents"])
        chunks = list(results["documents"][0]) if results and results["documents"] else []

        try:
            extra = 0
            for term in exact_terms(question):
                found = self.collection.get(where_document={"$contains": term}, limit=k, include=["documents"])
                for doc in found["documents"]:
                    if extra < KEYWORD_EXTRA and doc not in chunks:
                        chunks.append(doc)
                        extra += 1
        except Exception:
            logger.exception("Keyword lookup failed; returning vector results only")

        return chunks
