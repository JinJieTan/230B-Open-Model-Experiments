from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any

import requests


@dataclass
class ChatResult:
    content: str
    finish_reason: str | None
    usage: dict[str, Any]
    raw: dict[str, Any]


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout_sec: int = 600) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_sec = timeout_sec

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ChatResult:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            data=json.dumps(payload),
            timeout=self.timeout_sec,
        )

        response.raise_for_status()
        data = response.json()

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"Model response has no choices: {data}")

        first = choices[0]
        message = first.get("message", {})
        content = _normalize_message_content(message.get("content", ""))
        finish_reason = first.get("finish_reason")
        usage = data.get("usage", {})

        return ChatResult(
            content=content,
            finish_reason=finish_reason,
            usage=usage,
            raw=data,
        )


def _normalize_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()

    return str(content)


def load_client_from_env() -> tuple[OpenAICompatibleClient, str]:
    base_url = os.getenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    api_key = os.getenv("OPENAI_API_KEY", "") or None
    model_name = os.getenv("MODEL_NAME", "replace-with-your-model-name")
    timeout_sec = int(os.getenv("REQUEST_TIMEOUT_SEC", "600"))

    client = OpenAICompatibleClient(base_url=base_url, api_key=api_key, timeout_sec=timeout_sec)
    return client, model_name
