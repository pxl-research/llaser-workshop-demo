from AI.Chunking.Reranker import OpenRouterReranker

DEFAULT_RERANKER = "qwen/qwen3-reranker-8b"

AVAILABLE_RERANKERS = [
    {
        "name": "qwen/qwen3-reranker-8b",
        "source": "api",
        "description": "Qwen3 Reranker 8B via OpenRouter. Multilingual; passes Zero Data Retention.",
    },
]

_CATALOG = {entry["name"] for entry in AVAILABLE_RERANKERS}


def create_reranker_model(name: str):
    key = (name or "").strip().lower()
    if key not in _CATALOG:
        raise ValueError(f"Unknown RERANKER value: {name}")
    return OpenRouterReranker(model_id=key)
