import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from AI.Chunking.Reranker import OpenRouterReranker
from AI.API import metrics, rerankers


def client_returning(status, body, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def client_sequence(responses, seen=None):
    """Each item is an httpx.Response or an exception to raise, consumed in order."""
    queue = list(responses)

    def handler(request):
        if seen is not None:
            seen.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    return httpx.Client(transport=httpx.MockTransport(handler))


GOOD_BODY = {"results": [{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.4}]}


class OpenRouterRerankerTests(unittest.TestCase):
    def test_posts_rerank_request_and_orders_by_score(self):
        seen = []
        body = {"results": [{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.4}]}
        r = OpenRouterReranker("qwen/qwen3-reranker-8b", api_key="k", client=client_returning(200, body, seen))

        out = r.rerank("q", ["a", "b", "c"], top_n=2)

        self.assertEqual(out, ["c", "a"])
        req = seen[0]
        self.assertEqual(str(req.url), "https://openrouter.ai/api/v1/rerank")
        self.assertEqual(req.headers["Authorization"], "Bearer k")
        self.assertEqual(
            json.loads(req.content),
            {"model": "qwen/qwen3-reranker-8b", "query": "q", "documents": ["a", "b", "c"], "top_n": 2},
        )

    def test_provider_error_falls_back_visibly(self):
        r = OpenRouterReranker(
            "qwen/qwen3-reranker-8b", api_key="k", client=client_returning(503, {"error": "x"}), sleep=lambda s: None
        )
        before = metrics.rerank_fallback._value.get()

        with self.assertLogs("AI.Chunking.Reranker", level="WARNING") as logs:
            out = r.rerank("q", ["a", "b", "c"], top_n=2)

        self.assertEqual(out, ["a", "b"])
        self.assertIn("Rerank via OpenRouter failed", logs.output[0])
        self.assertIn("503", logs.output[0])
        self.assertEqual(metrics.rerank_fallback._value.get(), before + 1)

    def _assert_falls_back(self, client):
        r = OpenRouterReranker("qwen/qwen3-reranker-8b", api_key="k", client=client, sleep=lambda s: None)
        before = metrics.rerank_fallback._value.get()
        with self.assertLogs("AI.Chunking.Reranker", level="WARNING"):
            out = r.rerank("q", ["a", "b", "c"], top_n=2)
        self.assertEqual(out, ["a", "b"])
        self.assertEqual(metrics.rerank_fallback._value.get(), before + 1)

    def test_timeout_falls_back(self):
        def handler(request):
            raise httpx.ReadTimeout("t")
        self._assert_falls_back(httpx.Client(transport=httpx.MockTransport(handler)))

    def test_invalid_json_falls_back(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"not json")))
        self._assert_falls_back(client)

    def test_empty_results_fall_back(self):
        self._assert_falls_back(client_returning(200, {"results": []}))

    def test_out_of_range_index_falls_back(self):
        for index in (5, -1):
            with self.subTest(index=index):
                body = {"results": [{"index": index, "relevance_score": 0.9}]}
                self._assert_falls_back(client_returning(200, body))

    def test_empty_chunks_skip_request(self):
        seen = []
        r = OpenRouterReranker("qwen/qwen3-reranker-8b", api_key="k", client=client_returning(200, {}, seen))
        self.assertEqual(r.rerank("q", [], top_n=3), [])
        self.assertEqual(seen, [])

    def _retry_reranker(self, responses, seen=None):
        sleeps = []
        r = OpenRouterReranker(
            "qwen/qwen3-reranker-8b", api_key="k", client=client_sequence(responses, seen), sleep=sleeps.append
        )
        return r, sleeps

    def test_retries_once_on_503_then_succeeds(self):
        seen = []
        r, sleeps = self._retry_reranker([httpx.Response(503), httpx.Response(200, json=GOOD_BODY)], seen)
        before = metrics.rerank_fallback._value.get()

        with self.assertLogs("AI.Chunking.Reranker", level="INFO") as logs:
            out = r.rerank("q", ["a", "b", "c"], top_n=2)

        self.assertEqual(out, ["c", "a"])
        self.assertEqual(len(seen), 2)
        self.assertEqual(sleeps, [0.5])
        self.assertEqual(metrics.rerank_fallback._value.get(), before)
        self.assertEqual([rec for rec in logs.records if rec.levelname == "WARNING"], [])
        self.assertEqual([rec.levelname for rec in logs.records], ["INFO"])

    def test_two_transient_failures_fall_back_once(self):
        seen = []
        r, sleeps = self._retry_reranker([httpx.Response(503), httpx.Response(503)], seen)
        before = metrics.rerank_fallback._value.get()

        with self.assertLogs("AI.Chunking.Reranker", level="INFO") as logs:
            out = r.rerank("q", ["a", "b", "c"], top_n=2)

        self.assertEqual(out, ["a", "b"])
        self.assertEqual(len(seen), 2)
        self.assertEqual(len(sleeps), 1)
        self.assertEqual(len([rec for rec in logs.records if rec.levelname == "WARNING"]), 1)
        self.assertEqual(metrics.rerank_fallback._value.get(), before + 1)

    def test_non_transient_status_is_not_retried(self):
        for status in (400, 401, 402, 403, 404):
            with self.subTest(status=status):
                seen = []
                r, sleeps = self._retry_reranker([httpx.Response(status)], seen)
                before = metrics.rerank_fallback._value.get()
                with self.assertLogs("AI.Chunking.Reranker", level="WARNING"):
                    out = r.rerank("q", ["a", "b", "c"], top_n=2)
                self.assertEqual(out, ["a", "b"])
                self.assertEqual(len(seen), 1)
                self.assertEqual(sleeps, [])
                self.assertEqual(metrics.rerank_fallback._value.get(), before + 1)

    def test_retry_after_seconds_is_honored(self):
        r, sleeps = self._retry_reranker(
            [httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200, json=GOOD_BODY)]
        )
        self.assertEqual(r.rerank("q", ["a", "b", "c"], top_n=2), ["c", "a"])
        self.assertEqual(sleeps, [1.0])

    def test_retry_after_is_capped(self):
        r, sleeps = self._retry_reranker(
            [httpx.Response(429, headers={"Retry-After": "30"}), httpx.Response(200, json=GOOD_BODY)]
        )
        r.rerank("q", ["a", "b", "c"], top_n=2)
        self.assertEqual(sleeps, [2.0])

    def test_retry_after_non_numeric_uses_default(self):
        r, sleeps = self._retry_reranker(
            [httpx.Response(503, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
             httpx.Response(200, json=GOOD_BODY)]
        )
        r.rerank("q", ["a", "b", "c"], top_n=2)
        self.assertEqual(sleeps, [0.5])

    def test_timeout_is_retried(self):
        r, sleeps = self._retry_reranker([httpx.ReadTimeout("t"), httpx.Response(200, json=GOOD_BODY)])
        self.assertEqual(r.rerank("q", ["a", "b", "c"], top_n=2), ["c", "a"])
        self.assertEqual(sleeps, [0.5])

    def test_connection_error_is_retried(self):
        r, sleeps = self._retry_reranker([httpx.ConnectError("c"), httpx.Response(200, json=GOOD_BODY)])
        self.assertEqual(r.rerank("q", ["a", "b", "c"], top_n=2), ["c", "a"])
        self.assertEqual(sleeps, [0.5])

    def test_empty_results_are_not_retried(self):
        seen = []
        r, sleeps = self._retry_reranker([httpx.Response(200, json={"results": []})], seen)
        before = metrics.rerank_fallback._value.get()
        with self.assertLogs("AI.Chunking.Reranker", level="WARNING"):
            out = r.rerank("q", ["a", "b", "c"], top_n=2)
        self.assertEqual(out, ["a", "b"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(metrics.rerank_fallback._value.get(), before + 1)

    def test_missing_key_raises(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
                OpenRouterReranker("qwen/qwen3-reranker-8b")


class RerankerFactoryTests(unittest.TestCase):
    def test_catalog_and_default(self):
        self.assertEqual([r["name"] for r in rerankers.AVAILABLE_RERANKERS], ["qwen/qwen3-reranker-8b"])
        self.assertEqual(rerankers.DEFAULT_RERANKER, "qwen/qwen3-reranker-8b")

    def test_unknown_raises(self):
        for name in ("BAAI bge-reranker", "Colbert", ""):
            with self.assertRaises(ValueError):
                rerankers.create_reranker_model(name)
