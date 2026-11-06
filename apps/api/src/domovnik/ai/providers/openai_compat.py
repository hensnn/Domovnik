"""OpenAI-kompatibilní API (OpenAI, Ollama, LM Studio, vLLM, OpenRouter…)."""

from __future__ import annotations

import base64
import json
from typing import Any

from domovnik.ai.providers.base import (
    ChatResult,
    Message,
    NotConfigured,
    ProviderError,
    ToolCall,
    ToolSpec,
    Usage,
)
from domovnik.ai.providers.http import post_json


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str, embed_model: str = "") -> None:
        if not base_url:
            raise NotConfigured("Chybí URL OpenAI-kompatibilního API (Nastavení → AI asistent).")
        self.base_url = base_url.rstrip("/")
        self.api_key, self.model, self.embed_model = api_key, model, embed_model

    def _headers(self) -> dict[str, str]:
        h = {"content-type": "application/json"}
        if self.api_key:
            h["authorization"] = f"Bearer {self.api_key}"
        return h

    @staticmethod
    def _messages(messages: list[Message], system: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}] if system else []
        for m in messages:
            if m.role == "user":
                if m.images:
                    parts: list[dict[str, Any]] = [{"type": "text", "text": m.content or "."}]
                    for img in m.images:
                        uri = f"data:{img.mime};base64,{base64.b64encode(img.data).decode()}"
                        parts.append({"type": "image_url", "image_url": {"url": uri}})
                    out.append({"role": "user", "content": parts})
                else:
                    out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.content or None}
                if m.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in m.tool_calls
                    ]
                out.append(msg)
            else:
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        return out

    def chat(
        self,
        messages: list[Message],
        *,
        system: str = "",
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(messages, system),
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": json_schema},
            }
        data = post_json(
            f"{self.base_url}/chat/completions", headers=self._headers(), payload=payload
        )
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("Poskytovatel nevrátil žádnou odpověď.")
        msg = choices[0].get("message") or {}
        calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            calls.append(ToolCall(tc.get("id") or f"call_{len(calls)}", fn.get("name", ""), args))
        usage = data.get("usage") or {}
        return ChatResult(
            msg.get("content") or "",
            calls,
            Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
            self.model,
        )

    def embed(self, texts: list[str], *, dimensions: int = 1024) -> list[list[float]]:
        if not self.embed_model:
            raise NotConfigured("Není nastaven model pro embeddings.")
        payload: dict[str, Any] = {"model": self.embed_model, "input": texts}
        if dimensions:
            payload["dimensions"] = dimensions
        data = post_json(f"{self.base_url}/embeddings", headers=self._headers(), payload=payload)
        return [row["embedding"] for row in data.get("data", [])]
