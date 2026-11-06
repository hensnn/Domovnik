"""Anthropic Claude (Messages API, REST)."""

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

URL = "https://api.anthropic.com/v1/messages"
JSON_TOOL = "respond_json"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, embed_model: str = "") -> None:
        if not api_key:
            raise NotConfigured("Chybí Anthropic API klíč (Nastavení → AI asistent).")
        self.api_key, self.model = api_key, model

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    @staticmethod
    def _messages(messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                blocks: list[dict[str, Any]] = []
                for img in m.images:
                    blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": img.mime,
                                "data": base64.b64encode(img.data).decode(),
                            },
                        }
                    )
                blocks.append({"type": "text", "text": m.content or "."})
                out.append({"role": "user", "content": blocks})
            elif m.role == "assistant":
                blocks = [{"type": "text", "text": m.content}] if m.content else []
                for tc in m.tool_calls:
                    blocks.append(
                        {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                    )
                out.append(
                    {"role": "assistant", "content": blocks or [{"type": "text", "text": "."}]}
                )
            else:
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
                if (
                    out
                    and out[-1]["role"] == "user"
                    and isinstance(out[-1]["content"], list)
                    and out[-1]["content"]
                    and out[-1]["content"][0].get("type") == "tool_result"
                ):
                    out[-1]["content"].append(block)  # více výsledků nástrojů v jedné zprávě
                else:
                    out.append({"role": "user", "content": [block]})
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
            "max_tokens": 4096,
            "temperature": temperature,
            "messages": self._messages(messages),
        }
        if system:
            payload["system"] = system
        specs = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in (tools or [])
        ]
        if json_schema is not None:
            specs.append(
                {
                    "name": JSON_TOOL,
                    "description": "Vrať výsledek ve zvoleném formátu.",
                    "input_schema": json_schema,
                }
            )
            payload["tool_choice"] = {"type": "tool", "name": JSON_TOOL}
        if specs:
            payload["tools"] = specs

        data = post_json(URL, headers=self._headers(), payload=payload)
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                if json_schema is not None and block["name"] == JSON_TOOL:
                    text_parts.append(json.dumps(block.get("input", {}), ensure_ascii=False))
                else:
                    calls.append(ToolCall(block["id"], block["name"], block.get("input") or {}))
        if not text_parts and not calls:
            raise ProviderError("Claude nevrátil žádný obsah.")
        usage = data.get("usage") or {}
        return ChatResult(
            "".join(text_parts),
            calls,
            Usage(usage.get("input_tokens", 0), usage.get("output_tokens", 0)),
            self.model,
        )

    def embed(self, texts: list[str], *, dimensions: int = 1024) -> list[list[float]]:
        raise NotConfigured(
            "Anthropic nenabízí embeddings – vyber jiného providera pro embeddings."
        )
