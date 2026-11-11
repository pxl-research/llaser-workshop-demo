import asyncio
import importlib
import json
import logging
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

import httpx
import requests


PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))


SECRET_PATH = "/app/data/secret.pdf"
SECRET_KEY = "sk-or-XXXX"
DEFENSE_UNAVAILABLE_ANSWER = "query blocked: prompt defense unavailable, try again later"


class FakeSystem:
    def __init__(self, *args, **kwargs):
        self.processed_files = []

    def stream_query(self, question: str, session_id: str = None):
        yield "o"
        yield "k"
        return {"total_tokens": 2}

    def process_and_add_document(self, file_path: str):
        self.processed_files.append(file_path)
        return {"status": "success", "chunks": 1}

    def delete_document(self, file_path: str):
        self.deleted_files = [*getattr(self, "deleted_files", []), file_path]
        Path(file_path).unlink()


def sse_events(response):
    return [
        json.loads(line[len("data: "):])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def sse_answer(response):
    return "".join(event.get("delta", "") for event in sse_events(response))


class SafePromptDefense:
    def check_prompt_safety(self, prompt: str):
        return True, "safe"


class FakeMLPromptSafetyDetector:
    def __init__(self, *args, **kwargs):
        self.is_loaded = True

    def detect(self, prompt: str):
        return {"is_malicious": False}


class UnavailableMLPromptSafetyDetector:
    is_loaded = False

    def detect(self, prompt: str):
        raise AssertionError("detect should not be called when the detector is unavailable")


class MaliciousMLPromptSafetyDetector:
    is_loaded = True

    def detect(self, prompt: str):
        return {
            "is_malicious": True,
            "risk_level": "HIGH",
            "threat_types": ["prompt injection"],
        }


class FakePromptfoo:
    """promptfoo as the backend uses it, in memory: the web server (runs, one run's table, the grading e-mail)
    and the runner service (start a run, the current run)."""

    def __init__(self, runs=(), tables=None, email="host@example.com"):
        self.runs = list(runs)
        self.tables = tables or {}
        self.email = email
        self.started = []  # the bodies the runner received
        self.current_run = None  # what the runner reports as current
        self.requested = []

    def finish_run(self, run_id="eval-9"):
        self.current_run.update(status="complete", progress=self.current_run["total"], run_id=run_id)

    def request(self, method, url, json=None, timeout=None):
        self.requested.append((method, url))
        if url.startswith(settings.PROMPTFOO_RUNNER_URL):
            return self._runner(method, url.removeprefix(settings.PROMPTFOO_RUNNER_URL), json)
        path = url.removeprefix(settings.PROMPTFOO_URL)
        if path == "/api/results":
            return self._response(200, {"data": self.runs})
        if path == "/api/user/email":
            return self._response(200, {"email": self.email})
        eval_id = next(i for i in self.tables if path.startswith(f"/api/eval/{quote(i, safe='')}/table"))
        return self._response(200, self.tables[eval_id])

    def _runner(self, method, path, body):
        if method == "GET" and path == "/runs/current":
            return self._response(200, {"run": self.current_run})
        if method == "POST" and path == "/runs":
            if self.current_run and self.current_run["status"] == "running":
                return self._response(409, {"error": f"the run '{self.current_run['name']}' is still going"})
            self.started.append(body)
            self.current_run = {"name": body["name"], "attack_set": body["attack_set"], "status": "running",
                                "progress": 0, "total": 72, "run_id": None, "error": None}
            return self._response(202, {"started": body["name"]})
        raise AssertionError(f"unexpected runner request {method} {path}")

    @staticmethod
    def _response(status, body):
        def raise_for_status():
            if status >= 400:
                raise requests.HTTPError(f"HTTP {status}")
        return types.SimpleNamespace(status_code=status, raise_for_status=raise_for_status, json=lambda: body)


def install_api_dependency_stubs():
    rag_module = types.ModuleType("AI.API.RAG")
    rag_module.RAG = FakeSystem
    sys.modules["AI.API.RAG"] = rag_module

    prompt_defense_module = types.ModuleType("AI.API.Prompt_Defense")
    prompt_defense_module.PromptDefense = SafePromptDefense
    prompt_defense_module.spark_defense = SafePromptDefense
    prompt_defense_module.openrouter_defense = SafePromptDefense
    sys.modules["AI.API.Prompt_Defense"] = prompt_defense_module

    nlp_module = types.ModuleType("AI.API.Prompt_Defense_NLP")
    nlp_module.MLPromptSafetyDetector = FakeMLPromptSafetyDetector
    sys.modules["AI.API.Prompt_Defense_NLP"] = nlp_module


install_api_dependency_stubs()
api_module = importlib.import_module("AI.API.API")
from AI.API import alerts, readiness, redteam, services, settings  # noqa: E402
from AI.API.exceptions import DocumentProcessingError  # noqa: E402


class ApiTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        logging.disable(logging.CRITICAL)
        self._cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)

        alerts.alerts_store.clear()
        alerts.session_blocks.clear()
        services._system_instance = FakeSystem()
        services._prompt_defense = None
        services._ml_safety_detector = None
        services._warmup_started = False
        services._homebrew_status = "off"
        services._homebrew_error = None
        services._homebrew_backend = None
        services._nlp_defense_status = "off"
        services._nlp_defense_error = None
        settings.USE_HOMEBREW = False
        settings.USE_NLP_DEFENSE = False
        settings.SYSTEM_PROMPT = settings.DEFAULT_SYSTEM_PROMPT
        readiness.readiness.reset()
        readiness.readiness.mark_ready()
        settings.MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024
        settings.UPLOAD_DIR = Path("data")
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api_module.app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        os.chdir(self._cwd)
        self._tmpdir.cleanup()
        logging.disable(logging.NOTSET)

    async def test_query_accepts_valid_request(self):
        response = await self.client.post("/query", json={"question": "Hello", "session_id": "session-1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sse_answer(response), "ok")

    async def test_query_streams_answer_as_server_sent_events(self):
        response = await self.client.post("/query", json={"question": "Hello", "session_id": "session-1"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        self.assertEqual(sse_events(response), [{"delta": "o"}, {"delta": "k"}])

    async def test_query_reports_failure_mid_stream_as_error_event(self):
        class BrokenSystem:
            def stream_query(self, question: str, session_id: str = None):
                yield "partial"
                raise RuntimeError("provider down")

        services._system_instance = BrokenSystem()

        response = await self.client.post("/query", json={"question": "Hello", "session_id": "session-1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sse_events(response),
            [{"delta": "partial"}, {"error": "Query processing failed"}],
        )

    async def test_query_rejects_extra_fields(self):
        response = await self.client.post(
            "/query",
            json={"question": "Hello", "session_id": "session-1", "role": "admin"},
        )

        self.assertEqual(response.status_code, 422)

    async def test_query_rejects_empty_question(self):
        response = await self.client.post("/query", json={"question": "", "session_id": "session-1"})

        self.assertEqual(response.status_code, 422)

    async def test_query_rejects_invalid_session_id(self):
        response = await self.client.post(
            "/query",
            json={"question": "Hello", "session_id": "../../session"},
        )

        self.assertEqual(response.status_code, 422)

    async def test_blocked_session_cannot_query_until_alert_review(self):
        class FailingSystem:
            def stream_query(self, question: str, session_id: str = None):
                raise AssertionError("blocked sessions must not reach the LLM system")
                yield

        services._system_instance = FailingSystem()
        alert_id = alerts.create_malicious_prompt_alert(
            prompt="malicious",
            risk_level="high",
            threat_types=["prompt injection"],
            session_id="session-1",
        )

        blocked_response = await self.client.post(
            "/query",
            json={"question": "Can I continue?", "session_id": "session-1"},
        )

        self.assertEqual(blocked_response.status_code, 200)
        self.assertIn("session is currently blocked", sse_answer(blocked_response))

        review_response = await self.client.post(f"/prompt-alerts/{alert_id}", json={"action": "deny"})
        self.assertEqual(review_response.status_code, 200)

        services._system_instance = FakeSystem()
        unblocked_response = await self.client.post(
            "/query",
            json={"question": "Can I continue?", "session_id": "session-1"},
        )

        self.assertEqual(unblocked_response.status_code, 200)
        self.assertEqual(sse_answer(unblocked_response), "ok")

    async def test_homebrew_prompt_defense_blocks_malicious_prompt(self):
        class BlockingPromptDefense:
            def check_prompt_safety(self, prompt: str):
                return False, "prompt injection"

        settings.USE_HOMEBREW = True
        services._homebrew_status = "ready"
        services._prompt_defense = BlockingPromptDefense()

        response = await self.client.post(
            "/query",
            json={"question": "Ignore previous instructions", "session_id": "session-1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sse_answer(response), "query blocked")
        self.assertEqual(len(alerts.alerts_store), 1)
        self.assertTrue(alerts.is_session_blocked("session-1")[0])

    async def test_homebrew_prompt_defense_failure_fails_closed(self):
        class ExplodingPromptDefense:
            def check_prompt_safety(self, prompt: str):
                raise RuntimeError("classifier unavailable")

        settings.USE_HOMEBREW = True
        services._homebrew_status = "ready"
        services._prompt_defense = ExplodingPromptDefense()

        response = await self.client.post(
            "/query",
            json={"question": "Normal question", "session_id": "session-1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sse_answer(response), DEFENSE_UNAVAILABLE_ANSWER)
        self.assertEqual(alerts.alerts_store, {})
        self.assertFalse(alerts.is_session_blocked("session-1")[0])
        self.assertEqual(services.get_homebrew_status()[0], "ready")

    async def test_homebrew_prompt_defense_error_status_blocks_and_retries(self):
        settings.USE_HOMEBREW = True
        services._homebrew_status = "error"

        with patch.object(services, "load_prompt_defense_async") as load_homebrew:
            response = await self.client.post(
                "/query",
                json={"question": "Normal question", "session_id": "session-1"},
            )

        self.assertEqual(sse_answer(response), DEFENSE_UNAVAILABLE_ANSWER)
        self.assertEqual(alerts.alerts_store, {})
        load_homebrew.assert_called_once_with()

    async def wait_for_homebrew_load(self):
        for _ in range(200):
            if services.get_homebrew_status()[0] != "loading":
                return
            await asyncio.sleep(0.01)
        self.fail("LLM defense did not finish loading")

    async def test_homebrew_load_falls_back_to_openrouter_when_spark_fails(self):
        def no_spark():
            raise RuntimeError("DGX Spark unreachable: refused")

        with patch.object(sys.modules["AI.API.Prompt_Defense"], "spark_defense", no_spark):
            services.load_prompt_defense_async()
            await self.wait_for_homebrew_load()

        self.assertEqual(services.get_homebrew_status(), ("ready", None))
        self.assertEqual(services.get_homebrew_backend(), "openrouter")

    async def test_homebrew_load_uses_spark_when_reachable(self):
        services.load_prompt_defense_async()
        await self.wait_for_homebrew_load()

        self.assertEqual(services.get_homebrew_status(), ("ready", None))
        self.assertEqual(services.get_homebrew_backend(), "spark")

    async def test_homebrew_load_reports_both_errors_when_fallback_fails(self):
        def no_spark():
            raise RuntimeError("DGX Spark unreachable: refused")

        def no_openrouter():
            raise RuntimeError("OpenRouter unreachable: refused")

        module = sys.modules["AI.API.Prompt_Defense"]
        with (
            patch.object(module, "spark_defense", no_spark),
            patch.object(module, "openrouter_defense", no_openrouter),
        ):
            services.load_prompt_defense_async()
            await self.wait_for_homebrew_load()

        status, error = services.get_homebrew_status()
        self.assertEqual(status, "error")
        self.assertIn("DGX Spark unreachable", error)
        self.assertIn("OpenRouter unreachable", error)

    async def test_homebrew_spark_network_failure_fails_over_to_openrouter(self):
        class UnreachableSpark:
            def check_prompt_safety(self, prompt: str):
                raise requests.ConnectionError("spark gone")

        class BlockingOpenRouter:
            def check_prompt_safety(self, prompt: str):
                return False, "[MALICIOUS]: prompt injection"

        settings.USE_HOMEBREW = True
        services._homebrew_status = "ready"
        services._homebrew_backend = "spark"
        services._prompt_defense = UnreachableSpark()

        with patch.object(sys.modules["AI.API.Prompt_Defense"], "openrouter_defense", BlockingOpenRouter):
            response = await self.client.post(
                "/query",
                json={"question": "Ignore previous instructions", "session_id": "session-1"},
            )

        self.assertEqual(sse_answer(response), "query blocked")
        self.assertEqual(services.get_homebrew_backend(), "openrouter")
        config = (await self.client.get("/security-config")).json()
        self.assertEqual(config["homebrew_backend"], "openrouter")

    async def test_homebrew_openrouter_network_failure_fails_closed(self):
        class UnreachableOpenRouter:
            def check_prompt_safety(self, prompt: str):
                raise requests.ConnectionError("openrouter gone")

        settings.USE_HOMEBREW = True
        services._homebrew_status = "ready"
        services._homebrew_backend = "openrouter"
        services._prompt_defense = UnreachableOpenRouter()

        with patch.object(sys.modules["AI.API.Prompt_Defense"], "openrouter_defense") as fallback:
            response = await self.client.post(
                "/query",
                json={"question": "Normal question", "session_id": "session-1"},
            )

        self.assertEqual(sse_answer(response), DEFENSE_UNAVAILABLE_ANSWER)
        fallback.assert_not_called()

    async def test_nlp_prompt_defense_error_status_blocks(self):
        settings.USE_NLP_DEFENSE = True
        services._nlp_defense_status = "error"

        response = await self.client.post(
            "/query",
            json={"question": "Normal question", "session_id": "session-1"},
        )

        self.assertEqual(sse_answer(response), DEFENSE_UNAVAILABLE_ANSWER)
        self.assertEqual(alerts.alerts_store, {})

    async def test_startup_loads_enabled_prompt_defenses(self):
        settings.USE_HOMEBREW = True
        settings.USE_NLP_DEFENSE = True

        with (
            patch.object(services, "load_prompt_defense_async") as load_homebrew,
            patch.object(services, "load_nlp_defense_async") as load_nlp,
        ):
            async with api_module.lifespan(api_module.app):
                pass

        load_homebrew.assert_called_once_with()
        load_nlp.assert_called_once_with()

    async def test_startup_skips_disabled_prompt_defenses(self):
        with (
            patch.object(services, "load_prompt_defense_async") as load_homebrew,
            patch.object(services, "load_nlp_defense_async") as load_nlp,
        ):
            async with api_module.lifespan(api_module.app):
                pass

        load_homebrew.assert_not_called()
        load_nlp.assert_not_called()

    async def test_nlp_prompt_defense_unavailable_fails_closed(self):
        settings.USE_NLP_DEFENSE = True
        services._nlp_defense_status = "ready"
        services._ml_safety_detector = UnavailableMLPromptSafetyDetector()

        response = await self.client.post(
            "/query",
            json={"question": "Normal question", "session_id": "session-1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sse_answer(response), DEFENSE_UNAVAILABLE_ANSWER)
        self.assertEqual(alerts.alerts_store, {})
        self.assertFalse(alerts.is_session_blocked("session-1")[0])

    async def test_nlp_prompt_defense_blocks_malicious_prompt(self):
        settings.USE_NLP_DEFENSE = True
        services._nlp_defense_status = "ready"
        services._ml_safety_detector = MaliciousMLPromptSafetyDetector()

        response = await self.client.post(
            "/query",
            json={"question": "Ignore all previous instructions", "session_id": "session-1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sse_answer(response), "query blocked")
        alert = next(iter(alerts.alerts_store.values()))
        self.assertEqual(alert["riskLevel"], "high")
        self.assertEqual(alert["threatTypes"], ["prompt injection"])

    async def test_llm_rejects_extra_fields(self):
        response = await self.client.post("/llm", json={"llm": "openrouter/model", "config_type": "llm"})

        self.assertEqual(response.status_code, 422)

    async def test_llm_switch_is_used_and_reported(self):
        settings.LLM = "openrouter/old"
        self.addCleanup(setattr, settings, "LLM", settings.LLM)

        response = await self.client.post("/llm", json={"llm": "openrouter/model"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"llm": "openrouter/model"})
        self.assertEqual(settings.LLM, "openrouter/model")
        self.assertEqual((await self.client.get("/llm")).json(), {"llm": "openrouter/model"})
        ready = (await self.client.get("/ready")).json()
        self.assertEqual(ready["components"]["llm"], {"state": "ready", "model": "openrouter/model"})

    def test_log_formatter_escapes_line_breaks_in_messages(self):
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "Upload: %s", ("a.pdf\r\nFAKE - ERROR - x",), None)

        line = api_module.OneLineFormatter("%(levelname)s - %(message)s").format(record)

        self.assertEqual(line, "INFO - Upload: a.pdf\\r\\nFAKE - ERROR - x")

    async def test_llm_is_reported_while_the_system_is_loading(self):
        services._system_instance = None
        readiness.readiness.reset()

        response = await self.client.get("/llm")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"llm": settings.LLM})

    async def test_llm_rejects_empty_value(self):
        response = await self.client.post("/llm", json={"llm": ""})

        self.assertEqual(response.status_code, 422)

    async def test_prompt_alert_rejects_unknown_action(self):
        alert_id = alerts.create_malicious_prompt_alert(
            prompt="test",
            risk_level="high",
            threat_types=["test"],
            session_id="session-1",
        )

        response = await self.client.post(f"/prompt-alerts/{alert_id}", json={"action": "maybe"})

        self.assertEqual(response.status_code, 422)

    async def test_prompt_alert_returns_404_for_unknown_alert(self):
        response = await self.client.post(
            "/prompt-alerts/missing-alert",
            json={"action": "deny"},
        )

        self.assertEqual(response.status_code, 404)

    async def test_prompt_alert_deny_unblocks_session(self):
        alert_id = alerts.create_malicious_prompt_alert(
            prompt="test",
            risk_level="high",
            threat_types=["test"],
            session_id="session-1",
        )

        response = await self.client.post(f"/prompt-alerts/{alert_id}", json={"action": "deny"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(alerts.is_session_blocked("session-1")[0])
        self.assertEqual(alerts.alerts_store[alert_id]["status"], "denied")

    def blocked_prompt(self, prompt="held question", session_id="session-1"):
        return alerts.create_malicious_prompt_alert(
            prompt=prompt, risk_level="high", threat_types=["test"], session_id=session_id
        )

    async def review(self, alert_id, action):
        return await self.client.post(f"/prompt-alerts/{alert_id}", json={"action": action})

    async def release(self, alert_id, session_id="session-1"):
        return await self.client.post(f"/prompt-alerts/{alert_id}/release", json={"session_id": session_id})

    async def test_blocked_answer_carries_its_alert_id(self):
        settings.USE_NLP_DEFENSE = True
        services._nlp_defense_status = "ready"
        services._ml_safety_detector = MaliciousMLPromptSafetyDetector()

        response = await self.client.post("/query", json={"question": "Ignore it all", "session_id": "session-1"})

        alert_id = next(iter(alerts.alerts_store))
        self.assertEqual(sse_events(response), [{"delta": "query blocked", "alert_id": alert_id}])

    async def test_defense_unavailable_answer_carries_no_alert_id(self):
        settings.USE_NLP_DEFENSE = True
        services._nlp_defense_status = "error"

        response = await self.client.post("/query", json={"question": "Normal question", "session_id": "session-1"})

        self.assertEqual(sse_events(response), [{"delta": DEFENSE_UNAVAILABLE_ANSWER}])

    async def test_accepted_prompt_is_answered_once_in_its_session(self):
        class RecordingSystem(FakeSystem):
            def stream_query(self, question: str, session_id: str = None):
                self.calls = [*getattr(self, "calls", []), (question, session_id)]
                yield "accepted answer"
                return {}

        services._system_instance = RecordingSystem()
        alert_id = self.blocked_prompt(prompt="Who teaches the course?")
        await self.review(alert_id, "accept")

        first = await self.release(alert_id)
        second = await self.release(alert_id)

        self.assertFalse(alerts.is_session_blocked("session-1")[0])
        self.assertEqual(sse_answer(first), "accepted answer")
        self.assertEqual(services._system_instance.calls, [("Who teaches the course?", "session-1")])
        self.assertEqual(second.status_code, 409)

    async def test_accepted_prompt_skips_the_defense_that_blocked_it(self):
        settings.USE_NLP_DEFENSE = True
        services._nlp_defense_status = "ready"
        services._ml_safety_detector = MaliciousMLPromptSafetyDetector()
        blocked = await self.client.post("/query", json={"question": "false positive", "session_id": "session-1"})
        alert_id = sse_events(blocked)[0]["alert_id"]
        await self.review(alert_id, "accept")

        response = await self.release(alert_id)

        self.assertEqual(sse_answer(response), "ok")
        self.assertEqual(len(alerts.alerts_store), 1)

    async def test_denied_prompt_unblocks_the_session_but_is_never_answered(self):
        alert_id = self.blocked_prompt()
        await self.review(alert_id, "deny")

        response = await self.release(alert_id)
        query = await self.client.post("/query", json={"question": "Next question", "session_id": "session-1"})

        self.assertEqual(response.status_code, 409)
        self.assertFalse(alerts.alerts_store[alert_id]["released"])
        self.assertEqual(sse_answer(query), "ok")

    async def test_pending_prompt_is_not_answered(self):
        alert_id = self.blocked_prompt()

        self.assertEqual((await self.release(alert_id)).status_code, 409)
        self.assertFalse(alerts.alerts_store[alert_id]["released"])

    async def test_accepted_prompt_is_not_answered_to_another_session(self):
        alert_id = self.blocked_prompt(session_id="session-1")
        await self.review(alert_id, "accept")

        self.assertEqual((await self.release(alert_id, "session-attacker")).status_code, 409)
        self.assertFalse(alerts.alerts_store[alert_id]["released"])
        self.assertEqual((await self.release(alert_id, "session-1")).status_code, 200)

    async def test_accepted_prompt_without_session_is_not_answered(self):
        alert_id = self.blocked_prompt(session_id=None)
        await self.review(alert_id, "accept")

        self.assertEqual((await self.release(alert_id, "session-1")).status_code, 409)

    async def test_release_while_loading_keeps_the_prompt(self):
        alert_id = self.blocked_prompt()
        await self.review(alert_id, "accept")
        services._system_instance = None
        readiness.readiness.reset()

        response = await self.release(alert_id)

        self.assertEqual(response.status_code, 503)
        self.assertFalse(alerts.alerts_store[alert_id]["released"])

    async def test_release_validates_its_request(self):
        alert_id = self.blocked_prompt()
        await self.review(alert_id, "accept")
        url = f"/prompt-alerts/{alert_id}/release"

        for body in ({}, {"session_id": ""}, {"session_id": "../x"}, {"session_id": "session-1", "question": "x"}):
            self.assertEqual((await self.client.post(url, json=body)).status_code, 422, body)
        self.assertEqual((await self.release("missing")).status_code, 404)
        self.assertFalse(alerts.alerts_store[alert_id]["released"])

    async def test_alert_status_follows_the_review_and_hides_the_prompt(self):
        alert_id = self.blocked_prompt(prompt="secret attack text")
        status = lambda: self.client.get(f"/prompt-alerts/{alert_id}")  # noqa: E731

        first = await status()
        await self.review(alert_id, "accept")

        self.assertEqual(first.json(), {"status": "pending"})
        self.assertNotIn("secret attack text", first.text)
        self.assertEqual((await status()).json(), {"status": "accepted"})
        self.assertEqual((await self.client.get("/prompt-alerts/missing")).status_code, 404)

    async def test_upload_rejects_unsupported_extension(self):
        response = await self.client.post(
            "/upload-document",
            files={"file": ("payload.exe", b"not a document", "application/octet-stream")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"], "Unsupported document type. Allowed: .pdf"
        )

    async def test_upload_rejects_csv_with_allowed_list(self):
        response = await self.client.post(
            "/upload-document",
            files={"file": ("table.csv", b"a,b\n1,2\n", "text/csv")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"], "Unsupported document type. Allowed: .pdf"
        )

    async def test_upload_rejects_docx(self):
        response = await self.client.post(
            "/upload-document",
            files={"file": ("report.docx", b"PK", "application/octet-stream")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Unsupported document type. Allowed: .pdf")

    async def test_upload_rejects_oversized_file(self):
        settings.MAX_UPLOAD_SIZE_BYTES = 3

        response = await self.client.post(
            "/upload-document",
            files={"file": ("notes.pdf", b"abcd", "application/pdf")},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"], "Uploaded file is too large")
        self.assertFalse(Path("data/notes.pdf").exists())

    async def test_upload_normalizes_filename_and_processes_document(self):
        response = await self.client.post(
            "/upload-document",
            files={"file": ("../notes.pdf", b"hello", "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["filename"], "notes.pdf")
        self.assertEqual(body["chunks"], 1)
        self.assertEqual(Path("data/notes.pdf").read_bytes(), b"hello")

    async def test_upload_with_same_filename_replaces_the_old_version(self):
        Path("data").mkdir()
        Path("data/notes.pdf").write_text("existing")

        response = await self.client.post(
            "/upload-document",
            files={"file": ("notes.pdf", b"replacement", "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["filename"], "notes.pdf")
        self.assertEqual(Path("data/notes.pdf").read_bytes(), b"replacement")
        self.assertEqual(sorted(p.name for p in Path("data").iterdir()), ["notes.pdf"])

    async def test_oversized_replacement_keeps_the_old_version(self):
        Path("data").mkdir()
        Path("data/notes.pdf").write_text("existing")
        settings.MAX_UPLOAD_SIZE_BYTES = 3

        response = await self.client.post(
            "/upload-document",
            files={"file": ("notes.pdf", b"abcd", "application/pdf")},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(Path("data/notes.pdf").read_text(), "existing")
        self.assertEqual(sorted(p.name for p in Path("data").iterdir()), ["notes.pdf"])

    async def test_documents_lists_uploaded_files_only(self):
        Path("data/.llaser_store").mkdir(parents=True)
        for name in ["b.pdf", "a.pdf", "notes.csv", ".a.pdf.123.part", ".llaser_store/c.pdf"]:
            Path("data", name).write_text("x")

        response = await self.client.get("/documents")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"documents": ["a.pdf", "b.pdf"]})

    async def test_documents_is_empty_before_the_first_upload(self):
        response = await self.client.get("/documents")

        self.assertEqual(response.json(), {"documents": []})

    async def test_delete_document_removes_file_through_the_system(self):
        Path("data").mkdir()
        Path("data/notes.pdf").write_text("x")

        response = await self.client.delete("/documents/notes.pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Deleted notes.pdf.")
        self.assertEqual(services._system_instance.deleted_files, [str(Path("data/notes.pdf"))])
        self.assertFalse(Path("data/notes.pdf").exists())

    async def test_delete_unknown_document_returns_404(self):
        response = await self.client.delete("/documents/missing.pdf")

        self.assertEqual(response.status_code, 404)

    async def test_delete_rejects_unsupported_extension(self):
        response = await self.client.delete("/documents/notes.csv")

        self.assertEqual(response.status_code, 400)

    async def test_delete_never_leaves_the_upload_dir(self):
        Path("secret.pdf").write_text("x")
        Path("data").mkdir()

        response = await self.client.delete("/documents/..%2Fsecret.pdf")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Path("secret.pdf").exists())

    async def _upload_with_system(self, system):
        services._system_instance = system
        return await self.client.post(
            "/upload-document",
            files={"file": ("notes.pdf", b"hello", "application/pdf")},
        )

    async def test_upload_processing_failure_returns_curated_message(self):
        class FailingSystem(FakeSystem):
            def process_and_add_document(self, file_path: str):
                return {"status": "error", "message": DocumentProcessingError.INDEX_FAILED}

        response = await self._upload_with_system(FailingSystem())

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], DocumentProcessingError.INDEX_FAILED)

    async def test_upload_empty_document_returns_422_read_message(self):
        class EmptyDocSystem(FakeSystem):
            def process_and_add_document(self, file_path: str):
                return {"status": "error", "message": DocumentProcessingError.UNREADABLE}

        response = await self._upload_with_system(EmptyDocSystem())

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "The document could not be read or contains no text.")

    async def test_upload_error_result_with_foreign_text_is_not_echoed(self):
        class LeakySystem(FakeSystem):
            def process_and_add_document(self, file_path: str):
                return {"status": "error", "message": f"boom {SECRET_PATH} {SECRET_KEY}"}

        response = await self._upload_with_system(LeakySystem())

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], DocumentProcessingError.GENERIC)
        self.assertNotIn(SECRET_PATH, response.text)
        self.assertNotIn(SECRET_KEY, response.text)

    async def test_upload_unexpected_exception_does_not_echo_text(self):
        class RaisingSystem(FakeSystem):
            def process_and_add_document(self, file_path: str):
                raise RuntimeError(f"failed reading {SECRET_PATH} with key {SECRET_KEY}")

        response = await self._upload_with_system(RaisingSystem())

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Failed to upload file")
        self.assertNotIn(SECRET_PATH, response.text)
        self.assertNotIn(SECRET_KEY, response.text)

    async def test_health_responds_while_upload_is_processing(self):
        started = threading.Event()
        release = threading.Event()

        class BlockingSystem(FakeSystem):
            def process_and_add_document(self, file_path: str):
                started.set()
                if not release.wait(timeout=10):
                    raise RuntimeError("test never released the upload")
                return {"status": "success", "chunks": 3}

        services._system_instance = BlockingSystem()

        upload_task = asyncio.create_task(
            self.client.post(
                "/upload-document",
                files={"file": ("notes.pdf", b"hello", "application/pdf")},
            )
        )
        try:
            for _ in range(200):
                if started.is_set():
                    break
                await asyncio.sleep(0.05)
            self.assertTrue(started.is_set(), "upload never reached document processing")

            health = await asyncio.wait_for(self.client.get("/health"), timeout=5)
            self.assertEqual(health.status_code, 200)
            self.assertFalse(upload_task.done())
        finally:
            release.set()

        upload = await asyncio.wait_for(upload_task, timeout=10)
        self.assertEqual(upload.status_code, 200)
        self.assertEqual(upload.json()["chunks"], 3)

    async def test_same_name_uploads_never_replace_the_file_mid_processing(self):
        first_started = threading.Event()
        release = threading.Event()
        seen = []

        class RecordingSystem(FakeSystem):
            def process_and_add_document(self, file_path: str):
                before = Path(file_path).read_bytes()
                if not first_started.is_set():
                    first_started.set()
                    if not release.wait(timeout=10):
                        raise RuntimeError("test never released the upload")
                seen.append((before, Path(file_path).read_bytes()))
                return {"status": "success", "chunks": 1}

        services._system_instance = RecordingSystem()

        def post(body):
            return asyncio.create_task(
                self.client.post("/upload-document", files={"file": ("notes.pdf", body, "application/pdf")})
            )

        first = post(b"first")
        try:
            for _ in range(200):
                if first_started.is_set():
                    break
                await asyncio.sleep(0.05)
            self.assertTrue(first_started.is_set(), "upload never reached document processing")
            second = post(b"second")
            await asyncio.sleep(0.3)  # without serialization the second save replaces the file here
        finally:
            release.set()
        responses = await asyncio.wait_for(asyncio.gather(first, second), timeout=10)

        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(seen, [(b"first", b"first"), (b"second", b"second")])

    async def test_available_llms_sanitizes_provider_errors(self):
        with patch.object(
            api_module.requests,
            "get",
            side_effect=requests.Timeout("provider timed out"),
        ):
            response = await self.client.get("/available-llms")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Failed to fetch LLM models"})

    @staticmethod
    def _openrouter_get(zdr_ids, zdr_error=None):
        def get(url, timeout=None):
            response = types.SimpleNamespace(raise_for_status=lambda: None)
            if url.endswith("/models"):
                response.json = lambda: {"data": [
                    {"id": "openai/gpt-oss-120b", "name": "GPT OSS"},
                    {"id": "ibm-granite/granite-4.0-h-micro", "name": "Granite"},
                ]}
            elif url.endswith("/endpoints/zdr"):
                if zdr_error:
                    raise zdr_error
                response.json = lambda: {"data": [{"model_id": i} for i in zdr_ids]}
            else:
                raise AssertionError(f"unexpected url {url}")
            return response
        return get

    async def test_available_llms_only_returns_zdr_models(self):
        with patch.object(api_module.requests, "get", side_effect=self._openrouter_get(["openai/gpt-oss-120b"])):
            response = await self.client.get("/available-llms")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([m["id"] for m in response.json()], ["openai/gpt-oss-120b"])

    async def test_available_llms_zdr_failure_returns_502(self):
        get = self._openrouter_get([], zdr_error=requests.ConnectionError("zdr down"))
        with patch.object(api_module.requests, "get", side_effect=get):
            response = await self.client.get("/available-llms")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Failed to fetch LLM models"})

    async def test_ready_reports_loading_state(self):
        services._system_instance = None
        readiness.readiness.reset()
        readiness.readiness.set_component_loading("embedding", model="baai/bge-m3")

        response = await self.client.get("/ready")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "loading")
        self.assertEqual(body["components"]["embedding"]["state"], "loading")
        self.assertEqual(body["components"]["embedding"]["model"], "baai/bge-m3")

    async def test_health_and_ready_endpoints(self):
        health_response = await self.client.get("/health")
        ready_response = await self.client.get("/ready")

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.json(), {"status": "ok"})
        self.assertEqual(ready_response.status_code, 200)
        self.assertEqual(ready_response.json()["status"], "ready")

    async def test_query_returns_503_when_system_is_not_ready(self):
        services._system_instance = None
        readiness.readiness.reset()
        readiness.readiness.set_component_loading("embedding", model="baai/bge-m3")

        response = await self.client.post(
            "/query",
            json={"question": "Hello", "session_id": "session-1"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "System is still starting")

    async def test_upload_returns_503_when_system_is_not_ready(self):
        services._system_instance = None
        readiness.readiness.reset()
        readiness.readiness.set_component_loading("embedding", model="baai/bge-m3")

        response = await self.client.post(
            "/upload-document",
            files={"file": ("notes.pdf", b"hello", "application/pdf")},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "System is still starting")

    async def test_get_security_config_returns_current_state(self):
        settings.USE_HOMEBREW = True
        settings.USE_NLP_DEFENSE = False
        services._homebrew_status = "ready"

        response = await self.client.get("/security-config")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["use_homebrew"])
        self.assertFalse(data["use_nlp_defense"])
        self.assertEqual(data["homebrew_status"], "ready")
        self.assertEqual(data["nlp_defense_status"], "off")

    async def test_get_security_config_reports_detector_confidence_threshold(self):
        detector = types.SimpleNamespace(confidence_threshold=0.8)

        with patch.object(services, "get_ml_safety_detector", return_value=detector):
            response = await self.client.get("/security-config")

        self.assertEqual(response.status_code, 200)
        self.assertAlmostEqual(response.json()["nlp_confidence_threshold"], 0.8)

    async def test_post_security_config_triggers_async_load(self):
        settings.USE_HOMEBREW = False
        settings.USE_NLP_DEFENSE = False

        response = await self.client.post(
            "/security-config",
            json={"use_homebrew": True},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["use_homebrew"])
        self.assertTrue(settings.USE_HOMEBREW)
        self.assertIn(data["homebrew_status"], ("loading", "ready", "error"))

    async def test_post_security_config_disable_sets_status_off(self):
        settings.USE_HOMEBREW = True
        services._homebrew_status = "ready"

        response = await self.client.post(
            "/security-config",
            json={"use_homebrew": False},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["use_homebrew"])
        self.assertEqual(data["homebrew_status"], "off")

    async def test_post_security_config_rejects_invalid_threshold(self):
        response = await self.client.post(
            "/security-config",
            json={"nlp_confidence_threshold": 1.5},
        )
        self.assertEqual(response.status_code, 422)

    async def test_system_prompt_get_returns_active_and_default(self):
        settings.SYSTEM_PROMPT = "Custom {context}"

        response = await self.client.get("/system-prompt")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"prompt": "Custom {context}", "default_prompt": settings.DEFAULT_SYSTEM_PROMPT},
        )

    async def test_system_prompt_post_sets_prompt(self):
        response = await self.client.post("/system-prompt", json={"prompt": "Only facts. {context}"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["prompt"], "Only facts. {context}")
        self.assertEqual(settings.SYSTEM_PROMPT, "Only facts. {context}")

    async def test_system_prompt_post_null_resets_to_default(self):
        settings.SYSTEM_PROMPT = "Custom {context}"

        response = await self.client.post("/system-prompt", json={"prompt": None})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(settings.SYSTEM_PROMPT, settings.DEFAULT_SYSTEM_PROMPT)

    async def test_system_prompt_post_requires_context_placeholder(self):
        response = await self.client.post("/system-prompt", json={"prompt": "No placeholder"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("{context}", response.json()["detail"])
        self.assertEqual(settings.SYSTEM_PROMPT, settings.DEFAULT_SYSTEM_PROMPT)

    async def test_system_prompt_post_rejects_too_long_prompt(self):
        response = await self.client.post("/system-prompt", json={"prompt": "{context}" + "x" * 8000})

        self.assertEqual(response.status_code, 422)
        self.assertIn("8000", response.json()["detail"])


    # --- Automated red teaming page: the backend talks to promptfoo, inside the compose network ---

    @staticmethod
    def _run(eval_id, created_at, description=None, red_team=True, tests=72):
        return {"evalId": eval_id, "createdAt": created_at, "description": description,
                "isRedteam": red_team, "numTests": tests, "passRate": 90.0}

    @staticmethod
    def _table(tags=None, failed=5, errors=0):
        return {
            "table": {"head": {"prompts": [{"metrics": {
                "testPassCount": 67, "testFailCount": failed, "testErrorCount": errors}}]},
                "body": [{"outputs": [{"text": "LLASER's answer must not reach the page"}]}]},
            "config": {"tags": tags} if tags is not None else {},
        }

    async def _start(self, promptfoo, name="nlp-defense", attack_set="workshop"):
        with patch.object(redteam.requests, "request", side_effect=promptfoo.request):
            return await self.client.post("/redteam/runs", json={"name": name, "attack_set": attack_set})

    async def _current(self, promptfoo):
        with patch.object(redteam.requests, "request", side_effect=promptfoo.request):
            return await self.client.get("/redteam/runs/current")

    async def _list(self, promptfoo):
        with patch.object(redteam.requests, "request", side_effect=promptfoo.request):
            return await self.client.get("/redteam/runs")

    async def test_redteam_runs_lists_red_team_runs_newest_first(self):
        promptfoo = FakePromptfoo(
            runs=[
                self._run("eval-old", 1000, "baseline"),
                self._run("eval-smoke", 3000, red_team=False, tests=3),
                self._run("eval-new", 2000, "nlp-defense"),
            ],
            tables={
                "eval-old": self._table({"run": "baseline", "attack_set": "workshop",
                                         "llm": "meta-llama/llama-3.3-70b-instruct", "defenses": "off"}),
                "eval-new": self._table({"run": "nlp-defense", "attack_set": "workshop", "defenses": "nlp",
                                         "nlp_threshold": 0.7}, failed=2, errors=1),
            },
        )
        response = await self._list(promptfoo)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["promptfoo_ui_port"], settings.PROMPTFOO_UI_PORT)
        self.assertEqual([run["name"] for run in body["runs"]], ["nlp-defense", "baseline"])
        self.assertEqual(body["runs"][0], {
            "id": "eval-new",
            "name": "nlp-defense",
            "created_at": 2000,
            "attack_set": "workshop",
            "settings": {"defenses": "nlp", "nlp_threshold": "0.7"},
            "attacks": 72,
            "got_through": 2,
            "errors": 1,
        })

    async def test_redteam_runs_never_passes_on_attacks_or_answers(self):
        response = await self._list(FakePromptfoo([self._run("eval-1", 1000, "baseline")], {"eval-1": self._table({})}))

        self.assertNotIn("LLASER's answer", response.text)

    async def test_redteam_run_without_name_or_tags_is_still_listed(self):
        response = await self._list(FakePromptfoo([self._run("eval-cli", 1000)], {"eval-cli": self._table()}))

        run = response.json()["runs"][0]
        self.assertEqual((run["name"], run["attack_set"], run["settings"]), ("eval-cli", None, {}))

    async def test_redteam_runs_encodes_the_run_id_in_the_path(self):
        odd_id = "eval-1/../../api/eval/job?x=1"
        promptfoo = FakePromptfoo([self._run(odd_id, 1000, "odd")], {odd_id: self._table({})})
        await self._list(promptfoo)

        self.assertIn(
            ("GET", f"{settings.PROMPTFOO_URL}/api/eval/eval-1%2F..%2F..%2Fapi%2Feval%2Fjob%3Fx%3D1/table?limit=1"),
            promptfoo.requested,
        )

    async def test_redteam_runs_says_how_to_start_promptfoo_when_it_is_down(self):
        with patch.object(redteam.requests, "request", side_effect=requests.ConnectionError("no promptfoo")):
            response = await self.client.get("/redteam/runs")

        self.assertEqual(response.status_code, 503)
        self.assertIn("docker compose up -d", response.json()["detail"])

    async def test_redteam_runs_rejects_an_unexpected_promptfoo_format(self):
        response = await self._list(FakePromptfoo([self._run("eval-1", 1000, "baseline")], {"eval-1": {"table": {}}}))

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Traceback", response.text)

    async def test_redteam_runs_rejects_a_non_json_answer(self):
        def request(method, url, json=None, timeout=None):
            def not_json():
                raise ValueError("no JSON")
            return types.SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=not_json)

        with patch.object(redteam.requests, "request", side_effect=request):
            response = await self.client.get("/redteam/runs")

        self.assertEqual(response.status_code, 503)

    async def test_start_run_asks_the_runner_with_name_attack_set_and_settings(self):
        promptfoo = FakePromptfoo()

        response = await self._start(promptfoo, name="baseline-2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"name": "baseline-2", "attack_set": "workshop", "status": "running",
                                           "progress": 0, "total": 72, "run_id": None, "error": None})
        self.assertEqual(promptfoo.started, [{"name": "baseline-2", "attack_set": "workshop", "tags": {
            "llm": settings.LLM, "defenses": "off", "prompt": "default"}}])

    async def test_start_run_accepts_the_quick_attack_set(self):
        promptfoo = FakePromptfoo()

        response = await self._start(promptfoo, name="check-1", attack_set="quick")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(promptfoo.started[0]["attack_set"], "quick")

    async def test_start_run_records_defenses_and_a_custom_prompt(self):
        settings.USE_NLP_DEFENSE = True
        services._nlp_defense_status = "ready"
        settings.USE_HOMEBREW = True
        services._homebrew_status = "ready"
        services._homebrew_backend = "openrouter"
        settings.SYSTEM_PROMPT = "Only answer about the course.\n{context}"
        promptfoo = FakePromptfoo()

        await self._start(promptfoo)

        self.assertEqual(promptfoo.started[0]["tags"], {
            "llm": settings.LLM, "defenses": "llm+nlp", "prompt": "custom",
            "nlp_threshold": "0.5", "llm_defense_backend": "openrouter",
        })

    async def test_start_run_refuses_while_a_defense_is_not_active(self):
        settings.USE_HOMEBREW = True
        services._homebrew_status = "loading"
        promptfoo = FakePromptfoo()

        response = await self._start(promptfoo)

        self.assertEqual(response.status_code, 409)
        self.assertIn("the LLM defense is loading", response.json()["detail"])
        self.assertEqual(promptfoo.started, [])

    async def test_start_run_refuses_a_name_already_used(self):
        promptfoo = FakePromptfoo(runs=[self._run("eval-1", 1000, "baseline")])

        response = await self._start(promptfoo, name="baseline")

        self.assertEqual(response.status_code, 409)
        self.assertIn("already is a run named 'baseline'", response.json()["detail"])
        self.assertEqual(promptfoo.started, [])

    async def test_start_run_refuses_while_another_run_is_going_then_allows_it(self):
        promptfoo = FakePromptfoo()
        await self._start(promptfoo, name="first")

        second = await self._start(promptfoo, name="second")
        self.assertEqual(second.status_code, 409)
        self.assertIn("'first' is still going", second.json()["detail"])

        promptfoo.finish_run()
        third = await self._start(promptfoo, name="third")
        self.assertEqual(third.status_code, 200)
        self.assertEqual([body["name"] for body in promptfoo.started], ["first", "third"])

    async def test_start_run_needs_a_grading_email_but_never_returns_it(self):
        without_email = FakePromptfoo(email=None)
        response = await self._start(without_email)
        self.assertEqual(response.status_code, 409)
        self.assertIn("promptfoo config set email", response.json()["detail"])
        self.assertEqual(without_email.started, [])

        with_email = FakePromptfoo(email="host@example.com")
        started = await self._start(with_email)
        current = await self._current(with_email)
        self.assertNotIn("host@example.com", started.text + current.text)
        self.assertNotIn("host@example.com", json.dumps(with_email.started))

    async def test_start_run_validates_the_request(self):
        for body in (
            {"name": "../etc", "attack_set": "workshop"},
            {"name": "a b", "attack_set": "workshop"},
            {"name": "--config", "attack_set": "workshop"},
            {"name": "", "attack_set": "workshop"},
            {"name": "x" * 65, "attack_set": "workshop"},
            {"name": "ok", "attack_set": "../../app/data/secret"},
            {"name": "ok", "attack_set": "workshop", "config": {"providers": ["exec:id"]}},
        ):
            with self.subTest(body=body):
                response = await self.client.post("/redteam/runs", json=body)
                self.assertEqual(response.status_code, 422)

    async def test_start_run_when_promptfoo_or_the_runner_is_down(self):
        with patch.object(redteam.requests, "request", side_effect=requests.ConnectionError("no promptfoo")):
            response = await self.client.post("/redteam/runs", json={"name": "x"})
        self.assertEqual(response.status_code, 503)

        promptfoo = FakePromptfoo()

        def runner_down(method, url, json=None, timeout=None):
            if url.startswith(settings.PROMPTFOO_RUNNER_URL):
                raise requests.ConnectionError("no runner")
            return promptfoo.request(method, url, json=json, timeout=timeout)

        with patch.object(redteam.requests, "request", side_effect=runner_down):
            response = await self.client.post("/redteam/runs", json={"name": "x"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("docker compose up -d", response.json()["detail"])

    async def test_current_run_follows_the_runner(self):
        promptfoo = FakePromptfoo()
        self.assertEqual((await self._current(promptfoo)).json(), {"job": None})

        await self._start(promptfoo, name="baseline")
        promptfoo.current_run["progress"] = 30
        running = (await self._current(promptfoo)).json()["job"]
        self.assertEqual((running["status"], running["progress"], running["total"]), ("running", 30, 72))

        promptfoo.finish_run("eval-9")
        done = (await self._current(promptfoo)).json()["job"]
        self.assertEqual((done["status"], done["progress"], done["run_id"]), ("complete", 72, "eval-9"))

    async def test_current_run_rejects_an_unexpected_runner_answer(self):
        promptfoo = FakePromptfoo()
        promptfoo.current_run = {"name": "x", "status": "flying"}

        response = await self._current(promptfoo)

        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
