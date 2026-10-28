import os

from openai import OpenAI

from AI.API import settings

_MAX_BATCH_SIZE = 64
_MAX_INPUT_CHARS = 8000


class OpenAIEmbeddingModel:
    """Embeddings from OpenRouter's OpenAI-compatible API."""

    def __init__(self, model_id: str, client=None):
        self.model_id = model_id
        if client is None:
            api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
            if not api_key:
                raise RuntimeError("Embeddings require OPENROUTER_API_KEY")
            client = OpenAI(
                api_key=api_key, base_url="https://openrouter.ai/api/v1", timeout=settings.PROVIDER_TIMEOUT_SECONDS
            )
        self.client = client

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prepared = [_prepare_embedding_text(text) for text in texts]
        vectors: list[list[float]] = []

        for start in range(0, len(prepared), _MAX_BATCH_SIZE):
            batch = prepared[start : start + _MAX_BATCH_SIZE]
            try:
                response = self.client.embeddings.create(model=self.model_id, input=batch)
            except Exception as exc:
                raise RuntimeError("Embedding provider request failed") from exc

            items = getattr(response, "data", None)
            if not items:
                raise RuntimeError("Embedding provider returned no vectors")

            ordered = sorted(items, key=lambda item: getattr(item, "index", 0))
            if len(ordered) != len(batch):
                raise RuntimeError("Embedding provider returned an unexpected vector count")
            vectors.extend(item.embedding for item in ordered)

        return vectors


def _prepare_embedding_text(text) -> str:
    stripped = str(text).strip() or " "
    return stripped[:_MAX_INPUT_CHARS]
