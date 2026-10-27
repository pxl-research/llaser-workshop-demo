import os
from typing import List, Union

import numpy as np
from openai import AzureOpenAI, OpenAI

from AI.API import settings
from AI.Chunking.Embedding_Provider import BaseEmbeddingModel

_MAX_BATCH_SIZE = 64
_MAX_INPUT_CHARS = 8000


def _https_url(value: str, name: str) -> str:
    url = (value or "").strip()
    if not url.startswith(("http://", "https://")):
        raise RuntimeError(f"{name} must be an http(s) URL")
    return url


_OPENROUTER_PROVIDER = "openrouter"


def create_embedding_client():
    """Create an embeddings client from environment configuration.

    Preference order:
    1. Azure OpenAI when AZURE_ENDPOINT is set
    2. OpenAI when OPENAI_API_KEY is set
    3. OpenRouter as an OpenAI-compatible fallback
    """
    return _build_embedding_client()[0]


def _openrouter_client(timeout):
    openrouter_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not openrouter_key:
        return None
    return OpenAI(
        api_key=openrouter_key,
        base_url="https://openrouter.ai/api/v1",
        timeout=timeout,
    )


def _build_embedding_client(openrouter_only: bool = False):
    """Return (client, provider) where provider is azure, openai or openrouter.

    openrouter_only=True skips Azure/OpenAI and requires OPENROUTER_API_KEY.
    """
    timeout = settings.PROVIDER_TIMEOUT_SECONDS
    if openrouter_only:
        client = _openrouter_client(timeout)
        if client is None:
            raise RuntimeError("This embedding model requires OPENROUTER_API_KEY")
        return client, _OPENROUTER_PROVIDER

    azure_endpoint = (os.getenv("AZURE_ENDPOINT") or "").strip()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    openai_base_url = (os.getenv("OPENAI_BASE_URL") or "").strip()

    if azure_endpoint:
        if not openai_key:
            raise RuntimeError("Azure embeddings require OPENAI_API_KEY")
        client = AzureOpenAI(
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            azure_endpoint=_https_url(azure_endpoint, "AZURE_ENDPOINT"),
            api_key=openai_key,
            timeout=timeout,
        )
        return client, "azure"

    if openai_key:
        kwargs = {"api_key": openai_key, "timeout": timeout}
        if openai_base_url:
            kwargs["base_url"] = _https_url(openai_base_url, "OPENAI_BASE_URL")
        return OpenAI(**kwargs), "openai"

    client = _openrouter_client(timeout)
    if client is not None:
        return client, _OPENROUTER_PROVIDER

    raise RuntimeError(
        "API embeddings require OPENAI_API_KEY, AZURE_ENDPOINT plus OPENAI_API_KEY, "
        "or OPENROUTER_API_KEY"
    )


class OpenAIEmbeddingModel(BaseEmbeddingModel):
    def __init__(self, model_id: str, client=None, openrouter_only: bool = False):
        if not model_id or not str(model_id).strip():
            raise ValueError("OpenAI embedding model_id is required")
        self.model_id = model_id
        provider = None
        if client is None:
            client, provider = _build_embedding_client(openrouter_only)
        self.client = client
        # OpenRouter expects provider-prefixed ids; Azure/OpenAI need the bare id.
        self.request_model_id = (
            f"openai/{model_id}"
            if provider == _OPENROUTER_PROVIDER and "/" not in model_id
            else model_id
        )

    def embed_documents(
        self,
        texts: List[str],
        normalize: bool = False,
        to_list: bool = True,
    ) -> Union[List[List[float]], np.ndarray]:
        if not texts:
            empty = np.zeros((0, 0), dtype=np.float32)
            return empty.tolist() if to_list else empty

        prepared = [_prepare_embedding_text(text) for text in texts]
        vectors: list[list[float]] = []

        for start in range(0, len(prepared), _MAX_BATCH_SIZE):
            batch = prepared[start : start + _MAX_BATCH_SIZE]
            try:
                response = self.client.embeddings.create(
                    model=self.request_model_id,
                    input=batch,
                )
            except Exception as exc:
                raise RuntimeError("Embedding provider request failed") from exc

            items = getattr(response, "data", None)
            if not items:
                raise RuntimeError("Embedding provider returned no vectors")

            ordered = sorted(items, key=lambda item: getattr(item, "index", 0))
            if len(ordered) != len(batch):
                raise RuntimeError("Embedding provider returned an unexpected vector count")
            vectors.extend(item.embedding for item in ordered)

        array = np.array(vectors, dtype=np.float32)
        if normalize:
            norms = np.linalg.norm(array, axis=1, keepdims=True) + 1e-12
            array = array / norms

        if to_list:
            return array.tolist()
        return array


def _prepare_embedding_text(text) -> str:
    if not isinstance(text, str):
        text = str(text)
    stripped = text.strip() or " "
    if len(stripped) > _MAX_INPUT_CHARS:
        return stripped[:_MAX_INPUT_CHARS]
    return stripped
