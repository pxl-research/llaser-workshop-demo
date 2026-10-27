import os
import uuid
from pathlib import Path

import anyio
from fastapi import HTTPException, UploadFile

from AI.API import settings


def normalize_upload_filename(filename: str) -> str:
    safe_filename = Path(filename.replace("\\", "/")).name
    if not safe_filename or safe_filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")

    extension = Path(safe_filename).suffix.lower()
    allowed = settings.allowed_document_extensions()
    if extension not in allowed:
        raise HTTPException(
            status_code=400, detail=f"Unsupported document type. Allowed: {', '.join(sorted(allowed))}"
        )

    return safe_filename


async def save_upload_file(file: UploadFile, destination: Path) -> int:
    """Write to a hidden temp file and swap it in, so a failed upload keeps the previous version."""
    temp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.part")
    bytes_written = 0
    try:
        async with await anyio.open_file(temp, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > settings.MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(status_code=413, detail="Uploaded file is too large")
                await f.write(chunk)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)

    return bytes_written
