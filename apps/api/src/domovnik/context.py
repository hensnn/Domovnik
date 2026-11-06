"""Kontext aktéra – kdo a odkud mění data. Předává se do každé zapisovací služby.

Hodnoty se na začátku transakce zapíšou do ``app.*`` (SET LOCAL), odkud je čte
audit trigger ``audit_row()`` – audit tak pokryje všechny kanály bez výjimky.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

Source = Literal["ui", "ai", "voice", "api", "mqtt", "import", "inventory", "system"]


@dataclass(frozen=True)
class ActorContext:
    actor_id: uuid.UUID | None
    source: Source = "ui"
    change_set_id: uuid.UUID | None = None
    request_id: str | None = None


SYSTEM = ActorContext(actor_id=None, source="system")


def bind_context(db: Session, ctx: ActorContext) -> None:
    """Nastaví audit proměnné pro aktuální transakci (``set_config(..., is_local=true)``)."""
    values = {
        "app.actor_id": str(ctx.actor_id) if ctx.actor_id else "",
        "app.source": ctx.source,
        "app.change_set_id": str(ctx.change_set_id) if ctx.change_set_id else "",
        "app.request_id": ctx.request_id or "",
    }
    for key, value in values.items():
        db.execute(text("SELECT set_config(:k, :v, true)"), {"k": key, "v": value})
