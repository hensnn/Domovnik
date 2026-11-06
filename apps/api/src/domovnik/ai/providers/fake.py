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


DEMO_DETECTIONS: dict[str, Any] = {
    "scene": "Police s nářadím a kabely",
    "location_hint": None,
    "detections": [
        {
            "label": "akušroubovák",
            "name": "Akušroubovák",
            "description": "Modrý aku šroubovák v kufru",
            "bbox": [0.05, 0.10, 0.40, 0.45],
            "confidence": 0.93,
            "quantity": 1,
            "brand": "Bosch",
            "model": "GSR 18V",
            "text_read": "Bosch Professional",
            "category_path": ["Nářadí", "Elektrické"],
            "tags": ["nářadí"],
            "unit": "ks",
            "notes": None,
        },
        {
            "label": "svinovací metr",
            "name": "Metr svinovací",
            "description": "Žlutý svinovací metr 5 m",
            "bbox": [0.55, 0.15, 0.20, 0.20],
            "confidence": 0.84,
            "quantity": 2,
            "brand": None,
            "model": None,
            "text_read": "5 m",
            "category_path": ["Nářadí", "Ruční"],
            "tags": [],
            "unit": "ks",
            "notes": None,
        },
        {
            "label": "kabely",
            "name": "Prodlužovací kabel",
            "description": "Svinutý černý kabel",
            "bbox": [0.10, 0.60, 0.35, 0.30],
            "confidence": 0.62,
            "quantity": 1,
            "brand": None,
            "model": None,
            "text_read": None,
            "category_path": ["Elektronika", "Kabely"],
            "tags": ["elektro"],
            "unit": "ks",
            "notes": "Délka nejasná",
        },
    ],
}


class DemoProvider(FakeProvider):
    """Vývojový „asistent“ bez API klíče (zapíná se proměnnou DOMOVNIK_FAKE_AI=1).

    Umí jednoduché hledání („kde mám X“) a vrací ukázkové detekce při čtení fotky.
    Slouží k ladění UI; nejde o skutečnou AI.
    """

    name = "demo"
    model = "demo"

    def chat(
        self,
        messages: list[Message],
        *,
        system: str = "",
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        import json

        if json_schema is not None:
            return text(json.dumps(DEMO_DETECTIONS, ensure_ascii=False))
        last = messages[-1]
        if last.role == "tool":
            try:
                data = json.loads(last.content)
            except ValueError:
                data = {}
            found = data.get("items") or []
            if not found:
                return text("V testovacím režimu jsem nic nenašel.")
            first = found[0]
            where = (first.get("locations") or [{}])[0].get("path") or "bez umístění"
            return text(f"{first['name']} je v umístění {where}. (testovací režim)")
        words = [w.strip("?.!,") for w in last.content.split() if len(w.strip("?.!,")) > 2]
        if words and any(k in last.content.lower() for k in ("kde", "najdi", "mám")):
            return call("search_items", query=words[-1])
        return text("Jsem testovací režim asistenta (DOMOVNIK_FAKE_AI). Zkus „Kde mám kladivo?“.")
