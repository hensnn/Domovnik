"""Jednotné rozhraní poskytovatelů LLM: chat + volání nástrojů + obrázky + strukturovaný výstup."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


class ProviderError(Exception):
    """Obecná chyba poskytovatele (síť, 5xx, neplatná odpověď)."""


class RateLimited(ProviderError):
    """Poskytovatel vrátil 429 / vyčerpanou kvótu."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class NotConfigured(ProviderError):
    """Chybí API klíč nebo URL."""


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema (type: object)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Image:
    mime: str
    data: bytes


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # role=assistant
    tool_call_id: str | None = None  # role=tool
    tool_name: str | None = None  # role=tool
    images: list[Image] = field(default_factory=list)


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class ChatResult:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    model: str = ""


class Provider(Protocol):
    name: str
    model: str

    def chat(
        self,
        messages: list[Message],
        *,
        system: str = "",
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        """Jedno kolo konverzace. S `json_schema` vrátí text jako JSON dle schématu."""
        ...

    def embed(self, texts: list[str], *, dimensions: int = 1024) -> list[list[float]]: ...
