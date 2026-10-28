import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from AI.API import settings  # noqa: E402

# Load from the file: test_api.py replaces AI.API.Prompt_Defense in sys.modules.
SOURCE = Path(__file__).resolve().parents[1] / "API" / "Prompt_Defense.py"

BASE_URL = "http://spark.test:8000"
MODEL = "Qwen/Qwen3.6-35B-A3B-FP8"


def load_prompt_defense_module():
    spec = importlib.util.spec_from_file_location("Prompt_Defense_under_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PD = load_prompt_defense_module()


def models_response(*model_ids):
    response = MagicMock()
    response.json.return_value = {"data": [{"id": model_id} for model_id in model_ids]}
    return response


def completion_response(content):
    response = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    return response


class PromptDefenseTests(unittest.TestCase):
    def setUp(self):
        for name, value in {
            "HOMEBREW_BASE_URL": BASE_URL,
            "HOMEBREW_API_KEY": "test-key",
            "HOMEBREW_MODEL": MODEL,
            "HOMEBREW_TIMEOUT_SECONDS": 7.0,
        }.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_defense(self):
        with patch("requests.get", return_value=models_response(MODEL)):
            return PD.spark_defense()

    def test_missing_base_url_raises(self):
        with patch.object(settings, "HOMEBREW_BASE_URL", ""):
            with self.assertRaisesRegex(RuntimeError, "HOMEBREW_BASE_URL"):
                PD.spark_defense()

    def test_unreachable_spark_raises(self):
        for exc in (requests.ConnectionError("refused"), requests.Timeout("slow")):
            with self.subTest(exc=type(exc).__name__):
                with patch("requests.get", side_effect=exc):
                    with self.assertRaisesRegex(RuntimeError, "DGX Spark unreachable"):
                        PD.spark_defense()

    def test_rejected_key_raises(self):
        response = models_response(MODEL)
        response.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized")
        with patch("requests.get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "DGX Spark rejected the request: 401"):
                PD.spark_defense()

    def test_probe_uses_homebrew_timeout(self):
        with patch("requests.get", return_value=models_response(MODEL)) as get:
            PD.spark_defense()

        args, kwargs = get.call_args
        self.assertEqual(args[0], f"{BASE_URL}/v1/models")
        self.assertEqual(kwargs["timeout"], 7.0)

    def test_model_not_served_raises(self):
        with patch("requests.get", return_value=models_response("other/model")):
            with self.assertRaisesRegex(RuntimeError, MODEL):
                PD.spark_defense()

    def test_safe_completion(self):
        defense = self.make_defense()
        with patch("requests.post", return_value=completion_response("[SAFE]")):
            self.assertEqual(defense.check_prompt_safety("hi"), (True, "[SAFE]"))

    def test_malicious_completion(self):
        defense = self.make_defense()
        content = "[MALICIOUS]: prompt injection"
        with patch("requests.post", return_value=completion_response(content)):
            self.assertEqual(defense.check_prompt_safety("hi"), (False, content))

    def test_untagged_completion_raises(self):
        defense = self.make_defense()
        with patch("requests.post", return_value=completion_response("not sure")):
            with self.assertRaises(ValueError):
                defense.check_prompt_safety("hi")

    def test_http_error_raises(self):
        defense = self.make_defense()
        response = completion_response("[SAFE]")
        response.raise_for_status.side_effect = requests.HTTPError("500")
        with patch("requests.post", return_value=response):
            with self.assertRaises(requests.HTTPError):
                defense.check_prompt_safety("hi")

    def test_request_details(self):
        defense = self.make_defense()
        with patch("requests.post", return_value=completion_response("[SAFE]")) as post:
            defense.check_prompt_safety("hi")

        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{BASE_URL}/v1/chat/completions")
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer test-key"})
        self.assertEqual(kwargs["timeout"], 7.0)
        body = kwargs["json"]
        self.assertEqual(body["model"], MODEL)
        self.assertEqual(body["temperature"], 0.1)
        self.assertEqual(body["max_tokens"], 100)
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        self.assertIn("hi", body["messages"][0]["content"])


class OpenRouterDefenseTests(unittest.TestCase):
    FALLBACK_MODEL = "qwen/qwen3-30b-a3b-instruct-2507"

    def setUp(self):
        patcher = patch.object(settings, "HOMEBREW_TIMEOUT_SECONDS", 7.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_uses_openrouter_key_and_fallback_model(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "or-key"}):
            with patch("requests.get", return_value=models_response(self.FALLBACK_MODEL)) as get:
                defense = PD.openrouter_defense()
            with patch("requests.post", return_value=completion_response("[SAFE]")) as post:
                defense.check_prompt_safety("hi")

        self.assertEqual(get.call_args.args[0], "https://openrouter.ai/api/v1/models")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer or-key"})
        self.assertEqual(kwargs["json"]["model"], self.FALLBACK_MODEL)

    def test_missing_openrouter_key_raises(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
                PD.openrouter_defense()

    def test_unreachable_openrouter_names_openrouter(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "or-key"}):
            with patch("requests.get", side_effect=requests.ConnectionError("refused")):
                with self.assertRaisesRegex(RuntimeError, "OpenRouter unreachable"):
                    PD.openrouter_defense()


if __name__ == "__main__":
    unittest.main()
