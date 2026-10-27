#!/usr/bin/env python3
# -----------------------------------------------------------------
# Vector Store
# -----------------------------------------------------------------
import os
import re
import hashlib
import logging
from abc import abstractmethod, ABC
from .Embedding_Provider import BaseEmbeddingModel

# Import ChromaDB
import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

# --- Utility Function ---
def compute_hash(file_path: str) -> str:
    """Computes the SHA256 hash of a file's content."""
    sha256_hash = hashlib.sha256()
    # Check if file exists to prevent FileNotFoundError
    if not os.path.exists(file_path):
        return "" 

    with open(file_path, "rb") as f:
        # Read and update hash in chunks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)

    return sha256_hash.hexdigest()

# Bump when stored vectors become incompatible with the current embedder
# (v2: OpenRouter embeddings replace in-process HuggingFace models).
_COLLECTION_VERSION = "v2"


def collection_name(prefix: str, model_name: str) -> str:
    """
    Builds a Chroma collection name that is unique per embedding model and store version,
    so incompatible vectors never share a collection.
    e.g. ("rag", "openai/text-embedding-3-small") -> "rag_v2_openai-text-embedding-3-small"
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (model_name or "").lower())
    head = f"{prefix}_{_COLLECTION_VERSION}_"
    # Chroma allows 3-512 chars and requires an alphanumeric first/last char.
    slug = slug[: 512 - len(head)].strip("-")
    if not slug:
        raise ValueError(f"Cannot derive a collection name from embedding model {model_name!r}")
    return f"{head}{slug}"

_MIGRATION_BATCH = 100
KEYWORD_EXTRA = 5
_EXACT_TERM = re.compile(r'"([^"]+)"|(\b[\w.-]*\d[\w.-]*\b)|(\b[A-Z]{2,}\b)')
_LEGACY_COLLECTION = re.compile(r"^(rag|session_memory)_(?!v\d+_)")


def _collection_names(client) -> list[str]:
    # chromadb versions differ: list_collections() yields names or Collection objects.
    return [getattr(c, "name", c) for c in client.list_collections()]


def _missing_rows(page, page_ids, existing) -> list[tuple]:
    """(id, document, metadata) rows of a page that the target lacks and that carry document text."""
    documents = page.get("documents") or [None] * len(page_ids)
    metadatas = page.get("metadatas") or [None] * len(page_ids)
    rows = []
    for row_id, doc, meta in zip(page_ids, documents, metadatas):
        if row_id in existing:
            continue
        if doc is None:
            logger.warning("Skipping chunk %s without document text", row_id)
            continue
        # Pass metadata through: Chroma rejects {} but accepts None.
        rows.append((row_id, doc, meta))
    return rows


def copy_missing_chunks(source_collection, target_collection) -> int:
    """
    Copy chunks of source_collection whose ids are missing from target_collection, page by page.
    Chunk ids are deterministic, so this is idempotent and resumable after a failure.
    Chroma re-embeds the documents with the target collection's embedding function.
    Returns the number of chunks added; errors propagate.
    """
    added = 0
    offset = 0
    while True:
        page = source_collection.get(include=["documents", "metadatas"], limit=_MIGRATION_BATCH, offset=offset)
        page_ids = page.get("ids") or []
        if not page_ids:
            break
        offset += len(page_ids)
        existing = set(target_collection.get(ids=page_ids, include=[])["ids"])
        rows = _missing_rows(page, page_ids, existing)
        if rows:
            target_collection.add(
                ids=[r[0] for r in rows], documents=[r[1] for r in rows], metadatas=[r[2] for r in rows]
            )
            added += len(rows)
    return added


def migrate_legacy_collection(store, prefix: str, model_name: str) -> int:
    """
    Copy chunks of every pre-v2 collection with this prefix (any embedding model, the current
    model's first so its version wins on duplicate ids) into the store's collection.
    Returns the number of chunks added; errors propagate so the caller keeps the legacy data.
    """
    current = collection_name(prefix, model_name).replace(f"{prefix}_{_COLLECTION_VERSION}_", f"{prefix}_", 1)
    legacy_names = sorted(
        (n for n in _collection_names(store.client) if n.startswith(f"{prefix}_") and _LEGACY_COLLECTION.match(n)),
        key=lambda n: n != current,
    )
    added = 0
    for name in legacy_names:
        moved = copy_missing_chunks(store.client.get_collection(name=name), store.collection)
        if moved:
            logger.info("Migrated %d chunks from %s to %s", moved, name, store.db_name)
        added += moved
    return added


def drop_legacy_collections(client) -> list[str]:
    """Delete unversioned rag_/session_memory_ collections left by older embedders."""
    dropped = [name for name in _collection_names(client) if _LEGACY_COLLECTION.match(name)]
    for name in dropped:
        client.delete_collection(name=name)
        logger.warning("Deleted legacy Chroma collection %s", name)
    return dropped


# -----------------------------------------------------------------
# Abstract Vector Store Base Class
# -----------------------------------------------------------------

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


class VectorStore(ABC):
    """
    Abstract base class for a vector store.
    """

    @abstractmethod
    def connect(self) -> None:
        """
        Abstract method to connect to the vector store.
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """
        Abstract method to close the connection to the vector store.
        """
        pass

    def __enter__(self):
        self.connect()
        return self # Return self to be used in 'with' statement

    def __exit__(self, exception_type, exception_value, exception_traceback):
        self.close()

    @abstractmethod
    def create(self) -> None:
        """
        Abstract method to create the internal database/collection for the vector store.
        """
        pass

    @abstractmethod
    def reset_collection(self) -> None:
        """
        Abstract method to delete/reset the main vector collection.
        """
        pass


# -----------------------------------------------------------------
# ChromaDB Vector Store Implementation
# -----------------------------------------------------------------

class CustomChromaEmbeddingFunction(embedding_functions.EmbeddingFunction):
    """Wraps the existing BaseEmbeddingModel to conform to Chroma's API."""
    def __init__(self, embedding_model: BaseEmbeddingModel):
        self.embedding_model = embedding_model

    # FIX APPLIED: Removed the problematic type hints (embedding_functions.Documents and 
    # embedding_functions.Embeddings) to resolve the AttributeError.
    def __call__(self, texts):
        # Use the existing embed_documents method
        # Chroma expects a list of list of floats (Embeddings)
        return self.embedding_model.embed_documents(
            texts, 
            normalize=False, 
            to_list=True # Ensure it returns a list of lists/vectors
        )


class ChromaVectorStore(VectorStore):
    def __init__(self, 
                 db_name: str, # Used as the Collection Name
                 embedding_model: BaseEmbeddingModel,
                 persist_directory: str = "chroma_db_data" # Directory for persistent storage
    ):
        self.client = None
        self.collection = None
        self.db_name = db_name # This will be the collection name
        self.persist_directory = persist_directory
        self.embedding_model = embedding_model
        
        # Initialize the custom embedding function for Chroma
        self.chroma_ef = CustomChromaEmbeddingFunction(embedding_model)

    def connect(self) -> None:
        """
        Connects to or initializes the ChromaDB client (persistent storage).
        """
        if self.client is not None:
            return
            
        # Initialize a PersistentClient. This loads or creates the DB on disk.
        self.client = chromadb.PersistentClient(path=self.persist_directory)

    def close(self) -> None:
        """
        Closes the connection. For persistent Chroma, this mostly ensures data is flushed to disk.
        """
        # No explicit close method for PersistentClient, but we can set client to None
        # to ensure reconnection/reinitialization if needed.
        self.client = None
        self.collection = None

    def reset_collection(self) -> None:
        """
        Deletes the Chroma collection (equivalent to dropping tables/schema in Postgres).
        """
        if self.client:
            # Drop the collection if it exists
            self.client.delete_collection(name=self.db_name)

    def create(self) -> None:
        """
        Creates the main Chroma collection, using the custom embedding function.
        In Chroma, a collection holds all the vectors, documents, and metadata.
        """
        if self.client is None:
            self.connect()
            
        # Get the collection. If it doesn't exist, Chroma creates it.
        # This is the rough equivalent of creating tables/schema.
        self.collection = self.client.get_or_create_collection(
            name=self.db_name,
            embedding_function=self.chroma_ef
        )
        logger.info("Chroma Collection '%s' ready in %s", self.db_name, self.persist_directory)

    def use_collection(self, db_name: str, embedding_model) -> None:
        """
        Points this store at another collection (never resetting the previous one)
        and embeds with the given model from now on.
        """
        self.db_name = db_name
        self.collection = None
        self.update_embedding_function(embedding_model)
        self.create()

    def get_collection(self, db_name: str, embedding_model):
        """Another collection on this client, embedding with embedding_model; the active one is unchanged."""
        if self.client is None:
            self.connect()
        return self.client.get_or_create_collection(
            name=db_name, embedding_function=CustomChromaEmbeddingFunction(embedding_model)
        )

    def is_indexed(self, file_path: str) -> bool:
        """True when a file with the same content hash is already in the collection."""
        if self.collection is None:
            self.create()
        file_hash = compute_hash(file_path)
        if not file_hash:
            return False
        return bool(self.collection.get(where={"file_hash": file_hash}, limit=1, include=[])["ids"])

    def prune_missing(self, keep_hashes: set[str]) -> None:
        """Delete chunks whose source content (file_hash) is no longer on disk; an empty set empties the collection."""
        if self.collection is None:
            self.create()
        if keep_hashes:
            self.collection.delete(where={"file_hash": {"$nin": sorted(keep_hashes)}})
            return
        # Chroma rejects an empty $nin
        ids = self.collection.get(include=[])["ids"]
        if ids:
            self.collection.delete(ids=ids)

    def add_document(self, file_path: str, chunks: list[str]) -> int:
        """
        Adds a document (split into chunks) to the Chroma collection.
        Chroma handles chunk storage, embedding generation, and indexing.

        Returns the number of chunks added, or 0 when nothing was added
        (empty input or the same file hash is already indexed).
        Raises RuntimeError when the collection insert fails.
        """
        if self.collection is None:
            self.create() # Ensure collection is initialized
        if not file_path or not chunks:
            return 0

        file_hash = compute_hash(file_path)

        # 1. Check for existing documents with the same hash
        # In Chroma, we must store the hash as metadata to check for duplicates.
        # We query by the metadata 'file_hash'
        results = self.collection.get(
            where={"file_hash": file_hash},
            limit=1,
            include=['metadatas']
        )
        
        if results and len(results['ids']) > 0:
            # File with the same content (hash) already exists
            file_path_in_db = results['metadatas'][0].get('file_path', 'Unknown Path')
            logger.info(
                "Document %s already indexed in the vector store (see %s)",
                file_path,
                file_path_in_db,
            )
            return 0

        # 2. Prepare data for insertion
        
        # Content-addressed IDs: a changed file at the same path never collides with old chunks
        ids = [f"{file_hash}_{i}" for i in range(len(chunks))]
        
        # Prepare metadata for each chunk (to link back to the document/file)
        metadatas = [
            {"file_path": file_path, "file_hash": file_hash, "chunk_index": i}
            for i in range(len(chunks))
        ]
        
        # 3. Insert into ChromaDB
        # The embedding function is set at the collection level, so we only pass the text (documents).
        try:
            self.collection.add(
                documents=chunks,
                metadatas=metadatas,
                ids=ids
            )
        except Exception as exc:
            logger.exception("Error adding document %s to Chroma: %s", file_path, exc)
            raise RuntimeError(f"Failed to add document to Chroma: {exc}") from exc

        logger.info("Added %d chunks for document: %s", len(chunks), file_path)
        return len(chunks)


    def retrieve_top_chunks(self, question: str, k: int) -> list[str]:
        """
        Similarity search, plus up to KEYWORD_EXTRA exact-term (keyword) matches for the reranker.
        """
        if self.collection is None:
            self.create()
            
        # Chroma handles the embedding of the query internally using the 
        # embedding_function provided during collection creation.
        results = self.collection.query(
            query_texts=[question],
            n_results=k,
            include=['documents', 'metadatas', 'distances'] # Request documents (chunks) and metadata
        )
        
        # The results are nested lists, extract the chunks (documents)
        chunks = list(results['documents'][0]) if results and results['documents'] else []

        try:
            extra = 0
            for term in exact_terms(question):
                found = self.collection.get(
                    where_document={"$contains": term}, limit=k, include=["documents"]
                )
                for doc in found["documents"]:
                    if extra < KEYWORD_EXTRA and doc not in chunks:
                        chunks.append(doc)
                        extra += 1
        except Exception:
            logger.exception("Keyword lookup failed; returning vector results only")

        return chunks

    def get_all_documents(self) -> dict:
        """
        Retrieve all documents and metadata from the vector store.
        
        Returns:
            dict with 'ids', 'documents', and 'metadatas' lists
        """
        if self.collection is None:
            return {"ids": [], "documents": [], "metadatas": []}
        
        try:
            # Get all documents without any queries (returns everything)
            results = self.collection.get(
                include=['documents', 'metadatas']
            )
            return results
        except Exception as e:
            logger.exception("Error retrieving all documents: %s", e)
            return {"ids": [], "documents": [], "metadatas": []}

    def update_embedding_function(self, new_embedding_model):
        """
        Update the embedding function for the vector store.
        
        Args:
            new_embedding_model: New BaseEmbeddingModel instance
        """
        self.embedding_model = new_embedding_model
        self.chroma_ef = CustomChromaEmbeddingFunction(new_embedding_model)
        if self.collection is not None:
            self.collection._embedding_function = self.chroma_ef
    

    