import json
import os
from typing import Optional

import requests

from AI.API import settings


def stream_text(model: str, system_prompt: str, user_message: str, history=(), max_new_tokens: int = 2048):
    """Yield answer text pieces as OpenRouter streams them, then return (usage, full_text).

    history: earlier (question, answer) pairs, oldest first, sent as real chat turns.
    """
    headers = {"Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY')}"}
    messages = [{"role": "system", "content": system_prompt}]
    for question, answer in history:
        messages += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    messages.append({"role": "user", "content": user_message})
    data = {
        "model": model,
        "messages": messages,
        "max_tokens": max_new_tokens,
        "temperature": 0.0,
        "stream": True,
    }

    with requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=data,
        stream=True,
        timeout=settings.LLM_TIMEOUT_SECONDS,
    ) as response:
        if response.status_code != 200:
            raise RuntimeError(f"OpenRouter API error: {response.text}")

        usage, finish_reason, pieces = {}, "unknown", []
        for raw_line in response.iter_lines():
            chunk = _parse_sse_line(raw_line)
            if chunk is None:
                continue
            usage = chunk.get("usage") or usage
            for choice in chunk.get("choices", [])[:1]:
                finish_reason = choice.get("finish_reason") or finish_reason
                text = (choice.get("delta") or {}).get("content")
                if text:
                    pieces.append(text)
                    yield text

    answer = "".join(pieces).strip()
    if not answer:
        answer = _empty_answer_message(finish_reason)
        yield answer
    return usage, answer


def _parse_sse_line(raw_line: bytes) -> Optional[dict]:
    """JSON payload of an SSE data line, None for other lines; raises on a stream error."""
    # Decode per line: requests guesses ISO-8859-1 for text/event-stream without a charset.
    line = raw_line.decode("utf-8")
    if not line.startswith("data: ") or line == "data: [DONE]":
        return None
    chunk = json.loads(line[len("data: "):])
    if "error" in chunk:
        raise RuntimeError(f"OpenRouter stream error: {chunk['error'].get('message')}")
    return chunk


def _empty_answer_message(finish_reason: str) -> str:
    if finish_reason == "length":
        return (
            "The model ran out of output tokens before completing its answer. "
            "Try a shorter question or choose another model."
        )
    return (
        "The model provider returned no text response "
        f"(finish reason: {finish_reason}). Please try again or choose another model."
    )
