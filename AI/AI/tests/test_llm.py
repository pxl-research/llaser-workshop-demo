import importlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_PARENT = Path(__file__).resolve().parents[2]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))


llm_module = importlib.import_module("AI.API.LLM")
LLM = llm_module.LLM


class FakeStreamResponse:
    def __init__(self, lines=(), status_code=200, text=""):
        self.status_code = status_code
        self.text = text
        self._lines = [line.encode("utf-8") for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        return iter(self._lines)


def sse_line(chunk):
    return "data: " + json.dumps(chunk)


def delta_chunk(content, finish_reason=None):
    return sse_line({"choices": [{"delta": {"content": content}, "finish_reason": finish_reason}]})


def usage_chunk(total_tokens, finish_reason="stop"):
    return sse_line({
        "choices": [{"delta": {"content": ""}, "finish_reason": finish_reason}],
        "usage": {"total_tokens": total_tokens},
    })


def drain(stream):
    pieces = []
    while True:
        try:
            pieces.append(next(stream))
        except StopIteration as stop:
            return pieces, stop.value


class LLMTestCase(unittest.TestCase):
    def stream(self, lines, status_code=200, text=""):
        response = FakeStreamResponse(lines, status_code=status_code, text=text)
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}, clear=False), \
             patch.object(llm_module.settings, "LLM_TIMEOUT_SECONDS", 7.5), \
             patch("AI.API.LLM.requests.post", return_value=response) as post:
            result = drain(LLM("test-model").stream_text("system", "hello"))
        return result, post

    def test_stream_text_yields_pieces_and_returns_usage_and_full_text(self):
        (pieces, (usage, answer)), post = self.stream([
            ": OPENROUTER PROCESSING",
            "",
            delta_chunk("Hello"),
            delta_chunk(" there"),
            usage_chunk(5),
            "data: [DONE]",
        ])

        self.assertEqual(pieces, ["Hello", " there"])
        self.assertEqual(usage, {"total_tokens": 5})
        self.assertEqual(answer, "Hello there")
        self.assertTrue(post.call_args.kwargs["stream"])
        self.assertTrue(post.call_args.kwargs["json"]["stream"])
        self.assertEqual(post.call_args.kwargs["timeout"], 7.5)

    def test_stream_text_decodes_utf8(self):
        (pieces, _), _ = self.stream([delta_chunk("café ✓"), usage_chunk(1), "data: [DONE]"])

        self.assertEqual(pieces, ["café ✓"])

    def test_stream_text_reports_empty_answer(self):
        (pieces, (_, answer)), _ = self.stream([delta_chunk(""), usage_chunk(3), "data: [DONE]"])

        self.assertEqual(len(pieces), 1)
        self.assertIn("returned no text response", answer)
        self.assertIn("stop", answer)

    def test_stream_text_reports_length_limit_clearly(self):
        (_, (_, answer)), _ = self.stream([usage_chunk(100, finish_reason="length"), "data: [DONE]"])

        self.assertIn("ran out of output tokens", answer)

    def test_stream_text_raises_on_http_error(self):
        with self.assertRaises(RuntimeError):
            self.stream([], status_code=401, text="bad key")

    def test_stream_text_raises_on_mid_stream_error(self):
        error_chunk = sse_line({
            "error": {"code": 502, "message": "provider down"},
            "choices": [{"delta": {}, "finish_reason": "error"}],
        })

        lines = [delta_chunk("Hel"), error_chunk, "data: [DONE]"]

        with self.assertRaisesRegex(RuntimeError, "provider down"):
            self.stream(lines)


if __name__ == "__main__":
    unittest.main()
