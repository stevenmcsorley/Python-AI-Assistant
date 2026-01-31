from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests

MODEL_NAME = "deepseek-chat"
MAX_TOKENS = 512
TEMPERATURE = 0.2
TIMEOUT_SECONDS = 30

_SYSTEM_PROMPT = (
    "You are a precise research assistant.\n"
    "You summarize and synthesize information without speculation.\n"
    "If information is missing, say so explicitly.\n"
    "Do not invent facts.\n"
)

_USER_PROMPT_TEMPLATE = (
    "Synthesize the following inputs into a concise summary.\n\n"
    "Requirements:\n"
    "- Be factual\n"
    "- Use short paragraphs or bullet points\n"
    "- Do not speculate\n"
    "- Do not include recommendations\n\n"
    "Inputs:\n"
    "{inputs_json}\n"
)


@dataclass(frozen=True)
class DeepSeekResponse:
    summary: str
    prompt_tokens: int
    completion_tokens: int


class DeepSeekError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def build_messages(inputs_json: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _USER_PROMPT_TEMPLATE.format(inputs_json=inputs_json)},
    ]


def run_chat_completion(
    api_key: str | None,
    api_base: str | None,
    inputs_json: str,
) -> DeepSeekResponse:
    if not api_key:
        raise DeepSeekError("missing_api_key")
    if not api_base:
        raise DeepSeekError("missing_api_base")

    url = api_base.rstrip("/") + "/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": MODEL_NAME,
        "messages": build_messages(inputs_json),
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise DeepSeekError(f"request_error:{exc}") from exc

    if response.status_code != 200:
        raise DeepSeekError(f"http_{response.status_code}")

    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise DeepSeekError("invalid_response") from exc

    choices = data.get("choices") or []
    if not choices:
        raise DeepSeekError("empty_response")

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not content or not isinstance(content, str) or not content.strip():
        raise DeepSeekError("empty_response")

    usage = data.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)

    return DeepSeekResponse(
        summary=content.strip(),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
