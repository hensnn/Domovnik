"""Google Gemini (Generative Language API, REST)."""

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

BASE = "https://generativelanguage.googleapis.com/v1beta"
_DROP = {"additionalProperties", "$schema", "default", "title", "examples", "$defs", "$ref"}


def clean_schema(schema: Any) -> Any:
    """Gemini přijímá jen podmnožinu OpenAPI schématu – odstraní nepodporované klíče."""
    if isinstance(schema, dict):
        out = {k: clean_schema(v) for k, v in schema.items() if k not in _DROP}
        # {"anyOf": [{"type": "string"}, {"type": "null"}]} → {"type": "string", "nullable": true}
        if "anyOf" in out:
            options = [o for o in out.pop("anyOf") if o.get("type") != "null"]
            if options:
                out.update(options[0])
                out["nullable"] = True
        if isinstance(out.get("type"), list):
            types = [t for t in out["type"] if t != "null"]
            out["type"] = types[0] if types else "string"
            out["nullable"] = True
        return out
    if isinstance(schema, list):
        return [clean_schema(x) for x in schema]
    return schema


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, embed_model: str = "") -> None:
        if not api_key:
            raise NotConfigured("Chybí Gemini API klíč (Nastavení → AI asistent).")
        self.api_key, self.model, self.embed_model = api_key, model, embed_model

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    @staticmethod
    def _contents(messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                parts: list[dict[str, Any]] = [{"text": m.content}] if m.content else []
                for img in m.images:
                    parts.append(
                        {
                            "inlineData": {
                                "mimeType": img.mime,
                                "data": base64.b64encode(img.data).decode(),
                            }
                        }
                    )
                out.append({"role": "user", "parts": parts or [{"text": ""}]})
            elif m.role == "assistant":
                parts = [{"text": m.content}] if m.content else []
                for tc in m.tool_calls:
                    parts.append({"functionCall": {"name": tc.name, "args": tc.arguments}})
                out.append({"role": "model", "parts": parts or [{"text": ""}]})
            else:  # tool
                try:
                    response: Any = json.loads(m.content)
                except ValueError:
                    response = m.content
                if not isinstance(response, dict):
                    response = {"result": response}
                out.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": m.tool_name or "tool",
                                    "response": response,
                                }
                            }
                        ],
                    }
                )
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
            "contents": self._contents(messages),
            "generationConfig": {"temperature": temperature},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parameters": clean_schema(t.parameters),
                        }
                        for t in tools
                    ]
                }
            ]
        if json_schema is not None:
            payload["generationConfig"]["responseMimeType"] = "application/json"
            payload["generationConfig"]["responseSchema"] = clean_schema(json_schema)

        data = post_json(
            f"{BASE}/models/{self.model}:generateContent", headers=self._headers(), payload=payload
        )
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "prázdná odpověď")
            raise ProviderError(f"Gemini nevrátilo odpověď ({reason}).")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought"))
        calls = [
            ToolCall(
                id=f"call_{i}_{p['functionCall']['name']}",
                name=p["functionCall"]["name"],
                arguments=p["functionCall"].get("args") or {},
            )
            for i, p in enumerate(x for x in parts if "functionCall" in x)
        ]
        meta = data.get("usageMetadata") or {}
        return ChatResult(
            text=text,
            tool_calls=calls,
            usage=Usage(meta.get("promptTokenCount", 0), meta.get("candidatesTokenCount", 0)),
            model=self.model,
        )

    def embed(self, texts: list[str], *, dimensions: int = 1024) -> list[list[float]]:
        if not self.embed_model:
            raise NotConfigured("Není nastaven model pro embeddings.")
        payload = {
            "requests": [
                {
                    "model": f"models/{self.embed_model}",
                    "content": {"parts": [{"text": t}]},
                    "outputDimensionality": dimensions,
                }
                for t in texts
            ]
        }
        data = post_json(
            f"{BASE}/models/{self.embed_model}:batchEmbedContents",
            headers=self._headers(),
            payload=payload,
        )
        return [e["values"] for e in data.get("embeddings", [])]
