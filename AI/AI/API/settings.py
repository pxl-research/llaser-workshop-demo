import os
from pathlib import Path


def env_flag(name: str, default: bool = False) -> bool:
    """Parse common boolean environment variable values."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


FRONTEND_URL = os.getenv("VITE_API_URL")
PROVIDER_TIMEOUT_SECONDS = float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "10"))
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
MAX_UPLOAD_SIZE_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(25 * 1024 * 1024)))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/app/data"))
# Vector stores and session memory persist here, inside the UPLOAD_DIR volume.
STORE_DIR = Path(os.getenv("STORE_DIR", str(UPLOAD_DIR / ".llaser_store")))
DEFAULT_DOCUMENT_LOADER = "azure_document_intelligence"
OFFICE_AND_PDF = {".pdf", ".docx", ".xlsx", ".pptx"}
LOADER_EXTENSIONS = {
    "azure_document_intelligence": OFFICE_AND_PDF,
    "llama_parse": OFFICE_AND_PDF,
    "pymupdf4llm": {".pdf"},
}


def allowed_document_extensions() -> set:
    """Extensions the active DOCUMENT_LOADER can read; unknown loaders allow nothing."""
    loader = os.getenv("DOCUMENT_LOADER") or DEFAULT_DOCUMENT_LOADER
    return LOADER_EXTENSIONS.get(loader, set())


SYSTEM_TYPE = os.getenv("SYSTEM_TYPE", "rag")
USE_HOMEBREW = env_flag("USE_HOMEBREW")
HOMEBREW_BASE_URL = os.getenv("HOMEBREW_BASE_URL", "").rstrip("/")
HOMEBREW_API_KEY = os.getenv("HOMEBREW_API_KEY", "")
HOMEBREW_MODEL = os.getenv("HOMEBREW_MODEL", "Qwen/Qwen3.6-35B-A3B-FP8")
HOMEBREW_TIMEOUT_SECONDS = float(os.getenv("HOMEBREW_TIMEOUT_SECONDS", "10"))
USE_NLP_DEFENSE = env_flag("USE_NLP_DEFENSE")
STATIC_CODE_ANALYSIS_VERIFIED = env_flag("STATIC_CODE_ANALYSIS_VERIFIED")
BACKGROUND_WARMUP = env_flag("BACKGROUND_WARMUP", default=True)
RAG_MAX_OUTPUT_TOKENS = int(os.getenv("RAG_MAX_OUTPUT_TOKENS", "2048"))

CORS_ORIGINS = [
    origin
    for origin in [
        "http://localhost:5173",
        FRONTEND_URL,
    ]
    if origin
]
CORS_METHODS = ["GET", "POST", "OPTIONS"]
CORS_HEADERS = ["Authorization", "Content-Type"]
