"""Výběr a sestavení poskytovatele AI podle nastavení (s záložním řetězem a limity)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from domovnik.ai.providers.anthropic import AnthropicProvider
from domovnik.ai.providers.base import (
    ChatResult,
    Message,
    NotConfigured,
    Provider,
    ProviderError,
    RateLimited,
    ToolSpec,
)
from domovnik.ai.providers.gemini import GeminiProvider
from domovnik.ai.providers.openai_compat import OpenAICompatProvider
from domovnik.services import settings as settings_service

Task = str  # "chat" | "vision" | "embeddings"

_override: Provider | None = None


def override_provider(provider: Provider | None) -> None:
    """Pro testy a ladění: všechna volání AI půjdou přes tento objekt."""
    global _override
    _override = provider


class QuotaGuard:
    """Lokální omezení počtu požadavků (ochrana free tieru): za minutu a za den."""

    def __init__(self) -> None:
        self._minute: deque[float] = deque()
        self._day = (date.today(), 0)

    def check(self, per_minute: int, per_day: int) -> None:
        now = time.monotonic()
        while self._minute and now - self._minute[0] > 60:
            self._minute.popleft()
        today, count = self._day
        if today != date.today():
            today, count = date.today(), 0
        if count >= per_day:
            raise RateLimited(f"Denní limit {per_day} požadavků na AI je vyčerpán.")
        if len(self._minute) >= per_minute:
            raise RateLimited(f"Limit {per_minute} požadavků za minutu – zkus to za chvíli.", 30.0)
        self._minute.append(now)
        self._day = (today, count + 1)

    @property
    def today_count(self) -> int:
        return self._day[1] if self._day[0] == date.today() else 0


quota = QuotaGuard()


def _build_one(db: Session, kind: str, model: str, embed_model: str) -> Provider:
    def get(key: str) -> str:
        return str(settings_service.get_value(db, key) or "")

    if kind == "gemini":
        return GeminiProvider(get("ai.gemini_api_key"), model, embed_model)
    if kind == "anthropic":
        return AnthropicProvider(get("ai.anthropic_api_key"), model)
    if kind in ("openai_compat", "ollama"):
        return OpenAICompatProvider(
            get("ai.openai_base_url"), get("ai.openai_api_key"), model, embed_model
        )
    raise NotConfigured(f"Neznámý provider „{kind}“.")


class FallbackProvider:
    """Zkusí hlavního providera; při limitu / chybě přepne na záložního."""

    def __init__(self, chain: list[Provider], guard: Callable[[], None]) -> None:
        self.chain, self._guard = chain, guard
        self.name = chain[0].name
        self.model = chain[0].model

    def chat(
        self,
        messages: list[Message],
        *,
        system: str = "",
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> ChatResult:
        self._guard()
        error: ProviderError | None = None
        for provider in self.chain:
            try:
                return provider.chat(
                    messages,
                    system=system,
                    tools=tools,
                    temperature=temperature,
                    json_schema=json_schema,
                )
            except ProviderError as exc:
                error = exc
        raise error or ProviderError("Žádný poskytovatel není k dispozici.")

    def embed(self, texts: list[str], *, dimensions: int = 1024) -> list[list[float]]:
        error: ProviderError | None = None
        for provider in self.chain:
            try:
                return provider.embed(texts, dimensions=dimensions)
            except ProviderError as exc:
                error = exc
        raise error or ProviderError("Žádný poskytovatel není k dispozici.")


def get_provider(db: Session, task: Task = "chat") -> Provider:
    """Provider pro danou úlohu (chat / vision / embeddings) dle nastavení."""
    if _override is not None:
        return _override

    def get(key: str) -> Any:
        return settings_service.get_value(db, key)

    if not get("ai.enabled"):
        raise NotConfigured("AI asistent je vypnutý (Nastavení → AI asistent).")
    kind = str(get(f"ai.provider_{'vision' if task == 'vision' else 'chat'}"))
    model = str(get("ai.model_vision" if task == "vision" else "ai.model_chat"))
    embed_model = str(get("ai.model_embeddings"))
    cloud = bool(get("ai.cloud_allowed"))

    def allowed(k: str) -> bool:
        return cloud or k in ("openai_compat", "ollama")

    if not allowed(kind):
        raise NotConfigured("Cloudové AI je zakázáno a vybraný provider je cloudový.")
    chain = [_build_one(db, kind, model, embed_model)]
    fallback = str(get("ai.provider_fallback"))
    if fallback not in ("none", kind) and allowed(fallback):
        with suppress(NotConfigured):  # záloha není nastavená – ignoruj
            chain.append(_build_one(db, fallback, _default_model(fallback, task), embed_model))
    per_min, per_day = int(get("ai.max_requests_per_minute")), int(get("ai.max_requests_per_day"))
    return FallbackProvider(chain, lambda: quota.check(per_min, per_day))


def _default_model(kind: str, task: Task) -> str:
    return {
        "gemini": "gemini-2.5-flash",
        "anthropic": "claude-sonnet-5-5",
        "openai_compat": "gpt-4o-mini",
        "ollama": "llama3.2-vision" if task == "vision" else "llama3.2",
    }.get(kind, "")
