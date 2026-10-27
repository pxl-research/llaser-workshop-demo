import logging
import os
import time
from typing import Callable, Optional

import httpx

from AI.API import metrics, settings

logger = logging.getLogger(__name__)

OPENROUTER_RERANK_URL = "https://openrouter.ai/api/v1/rerank"
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504, 524, 529}
RETRY_DEFAULT_DELAY = 0.5
RETRY_MAX_DELAY = 2.0


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


def _retry_delay(exc: Exception) -> float:
    header = exc.response.headers.get("Retry-After") if isinstance(exc, httpx.HTTPStatusError) else None
    try:
        return min(max(float(header), 0.0), RETRY_MAX_DELAY)
    except (TypeError, ValueError):
        return RETRY_DEFAULT_DELAY


class OpenRouterReranker:
    def __init__(
        self,
        model_id: str,
        api_key: Optional[str] = None,
        client: Optional[httpx.Client] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        key = (api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("Reranking requires OPENROUTER_API_KEY")
        self.model_id = model_id
        self._headers = {"Authorization": f"Bearer {key}"}
        self._client = client or httpx.Client(timeout=settings.PROVIDER_TIMEOUT_SECONDS)
        self._sleep = sleep

    def _post(self, question: str, chunks: list[str], top_n: int) -> httpx.Response:
        response = self._client.post(
            OPENROUTER_RERANK_URL,
            headers=self._headers,
            json={"model": self.model_id, "query": question, "documents": chunks, "top_n": top_n},
        )
        response.raise_for_status()
        return response

    def _post_with_retry(self, question: str, chunks: list[str], top_n: int) -> httpx.Response:
        """POST once more after a short backoff if the first attempt failed transiently."""
        try:
            return self._post(question, chunks, top_n)
        except httpx.HTTPError as exc:
            if not _is_transient(exc):
                raise
            logger.info(
                "Rerank via OpenRouter transient failure (model=%s, status=%s, error=%s); retrying once",
                self.model_id, getattr(getattr(exc, "response", None), "status_code", None), type(exc).__name__,
            )
            self._sleep(_retry_delay(exc))
            return self._post(question, chunks, top_n)

    def rerank(self, question: str, chunks: list[str], top_n: int = 5) -> list[str]:
        """Return the top_n chunks by relevance; keep vector order if the provider fails."""
        if not chunks:
            return []
        try:
            response = self._post_with_retry(question, chunks, top_n)
            results = response.json()["results"]
            if not results:
                raise ValueError("empty rerank results")
            for r in results:
                if not isinstance(r["index"], int) or not 0 <= r["index"] < len(chunks):
                    raise ValueError("rerank index out of range")
            ranked = sorted(results, key=lambda r: r["relevance_score"], reverse=True)
            return [chunks[r["index"]] for r in ranked[:top_n]]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning(
                "Rerank via OpenRouter failed (model=%s, status=%s, error=%s); using vector order",
                self.model_id, status, type(exc).__name__,
            )
            metrics.rerank_fallback.inc()
            return chunks[:top_n]
