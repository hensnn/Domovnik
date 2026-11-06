"""Sdílený HTTP klient poskytovatelů s překladem chyb a jednoduchým opakováním."""

from __future__ import annotations

import time
from typing import Any

import httpx

from domovnik.ai.providers.base import ProviderError, RateLimited

TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    retries: int = 2,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """POST JSON; 429 → RateLimited, 5xx a síťové chyby se zkusí znovu."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            if client is not None:
                resp = client.post(url, headers=headers, json=payload, timeout=TIMEOUT)
            else:
                resp = httpx.post(url, headers=headers, json=payload, timeout=TIMEOUT)
        except httpx.HTTPError as exc:
            last = ProviderError(f"Síťová chyba: {exc.__class__.__name__}")
            time.sleep(0.5 * (attempt + 1))
            continue
        if resp.status_code == 429:
            retry = resp.headers.get("retry-after")
            raise RateLimited(
                "Poskytovatel AI vrátil limit požadavků (429).",
                float(retry) if retry and retry.replace(".", "").isdigit() else None,
            )
        if resp.status_code >= 500:
            last = ProviderError(f"Chyba poskytovatele ({resp.status_code}).")
            time.sleep(0.5 * (attempt + 1))
            continue
        if resp.status_code >= 400:
            raise ProviderError(f"Požadavek odmítnut ({resp.status_code}): {resp.text[:300]}")
        try:
            return resp.json()  # type: ignore[no-any-return]
        except ValueError as exc:
            raise ProviderError("Neplatná odpověď poskytovatele (není JSON).") from exc
    raise last or ProviderError("Neznámá chyba poskytovatele.")
