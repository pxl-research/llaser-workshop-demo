from AI.Chunking.OpenAI_Embedding import OpenAIEmbeddingModel

DEFAULT_EMBEDDING_MODEL = "baai/bge-m3"

AVAILABLE_EMBEDDINGS = [
    {
        "name": DEFAULT_EMBEDDING_MODEL,
        "source": "api",
        "description": "BAAI BGE-M3 via OpenRouter. Multilingual, 1024 dimensions. Default.",
    },
    {
        "name": "openai/text-embedding-3-small",
        "source": "api",
        "description": "OpenAI text-embedding-3-small via Azure, OpenAI or OpenRouter. 1536 dimensions. Backup option.",
    },
]

# catalog name -> (request model id, OpenRouter only)
_MODELS = {
    DEFAULT_EMBEDDING_MODEL: (DEFAULT_EMBEDDING_MODEL, True),
    "openai/text-embedding-3-small": ("text-embedding-3-small", False),
}


def create_embedding_model(name: str):
    """Create an API embedding model from a catalog/env name."""
    key = (name or "").strip().lower()
    if not key:
        raise ValueError("EMBEDDING_MODEL is empty")
    if key not in _MODELS:
        raise ValueError(f"Unknown EMBEDDING_MODEL value: {name}")
    model_id, openrouter_only = _MODELS[key]
    return OpenAIEmbeddingModel(model_id=model_id, openrouter_only=openrouter_only)
