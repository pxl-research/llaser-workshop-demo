import logging
from pathlib import Path

from AI.API.exceptions import DocumentProcessingError


logger = logging.getLogger(__name__)


def process_uploaded_documents(
    system,
    uploaded_file_path: Path,
    uploaded_size: int,
):
    if not uploaded_file_path.is_file():
        raise FileNotFoundError(f"Uploaded file not found: {uploaded_file_path}")

    logger.debug("Processing uploaded document: %s", uploaded_file_path.name)
    try:
        result = system.process_and_add_document(file_path=str(uploaded_file_path))
        if not isinstance(result, dict) or result.get("status") != "success":
            user_message = result.get("message") if isinstance(result, dict) else None
            raise DocumentProcessingError(user_message)
    except Exception:
        # Unindexable files would be retried every restart; the user sees the error and re-uploads.
        # ponytail: a failed replacement leaves no version on disk; old chunks go at the next prune.
        uploaded_file_path.unlink(missing_ok=True)
        raise

    total_chunks = result.get("chunks", 0)
    already_indexed = bool(result.get("already_indexed", False))
    logger.info(
        "Document upload successful - File: %s, Chunks: %s, Already indexed: %s",
        uploaded_file_path.name,
        total_chunks,
        already_indexed,
    )
    if already_indexed:
        message = f"{uploaded_file_path.name} is already indexed."
    else:
        message = f"Uploaded and indexed {uploaded_file_path.name} ({total_chunks} chunks)."
    return {
        "status": "success",
        "filename": uploaded_file_path.name,
        "size": uploaded_size,
        "path": str(uploaded_file_path),
        "chunks": total_chunks,
        "already_indexed": already_indexed,
        "message": message,
    }
