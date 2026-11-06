"""Skriptovaný poskytovatel pro testy: vrací předem připravené odpovědi."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from domovnik.ai.providers.base import ChatResult, Message, ToolCall, ToolSpec, Usage

Step = ChatResult | Callable[[list[Message], str, list[ToolSpec]], ChatResult]


def text(value: str) -> ChatResult:
    return ChatResult(value, [], Usage(10, 5), "fake")


def call(name: str, **arguments: Any) -> ChatResult:
    return ChatResult("", [ToolCall(f"call_{name}", name, arguments)], Usage(10, 5), "fake")


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, script: list[Step] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[dict[str, Any]] = []
        self.embedding_dim = 1024

    def chat(
        self,
        messages: list[Message],
        *,
        system: str = "",
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        self.calls.append(
            {
                "messages": list(messages),
                "system": system,
                "tools": tools,
                "json_schema": json_schema,
            }
        )
        if not self.script:
            return text("(skript vyčerpán)")
        step = self.script.pop(0)
        return step(messages, system, tools or []) if callable(step) else step

    def embed(self, texts: list[str], *, dimensions: int = 1024) -> list[list[float]]:
        """Deterministické pseudo-embeddingy: podobné texty (společná slova) mají podobné vektory."""
        out = []
        for t in texts:
            vec = [0.0] * dimensions
            for word in t.lower().split():
                vec[hash(word) % dimensions] += 1.0
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out
