"""FastAPI závislosti: DB session, přihlášení (cookie / Bearer token), oprávnění, kontext."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from domovnik.context import ActorContext, bind_context
from domovnik.db import get_sessionmaker
from domovnik.errors import Forbidden, Unauthorized
from domovnik.services import auth as auth_service
from domovnik.services.auth import Principal

SESSION_COOKIE = "dmv_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_db() -> Iterator[Session]:
    """Session na jeden požadavek. Co není commitnuto, se při zavření vrátí zpět."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        principal = auth_service.resolve_token(db, header[7:].strip())
        if principal is None:
            raise Unauthorized("Neplatný nebo vypršelý token.")
        _persist(db)
        return principal

    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        principal = auth_service.resolve_session(db, raw)
        if principal is not None:
            if request.method not in SAFE_METHODS and (
                request.headers.get("x-csrf-token") != principal.csrf_token
            ):
                raise Forbidden("Chybí nebo nesouhlasí CSRF token.")
            _persist(db)
            return principal
    raise Unauthorized("Je potřeba se přihlásit.")


def _persist(db: Session) -> None:
    """Uloží drobné změny z ověření (last_seen / last_used)."""
    if db.dirty or db.new:
        db.commit()


@dataclass
class RequestCtx:
    db: Session
    principal: Principal
    ctx: ActorContext

    @property
    def user_id(self) -> uuid.UUID:
        return self.principal.user.id

    @property
    def is_admin(self) -> bool:
        return self.principal.user.role == "admin"

    def commit(self) -> None:
        self.db.commit()


def make_ctx(request: Request, principal: Principal, db: Session) -> RequestCtx:
    source = "api" if principal.auth_type == "token" else "ui"
    request_id = getattr(request.state, "request_id", None)
    ctx = ActorContext(actor_id=principal.user.id, source=source, request_id=request_id)  # type: ignore[arg-type]
    bind_context(db, ctx)
    return RequestCtx(db=db, principal=principal, ctx=ctx)


def require(scope: str) -> Callable[..., RequestCtx]:
    """Závislost: vyžaduje přihlášení a daný scope; vrací kontext požadavku."""

    def dependency(
        request: Request,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> RequestCtx:
        if not principal.has(scope):
            raise Forbidden(f"Chybí oprávnění „{scope}“.")
        return make_ctx(request, principal, db)

    return dependency


read = require("items:read")
own = read  # vlastní účet a tokeny: stačí být přihlášen
write = require("items:write")
files_write = require("files:write")
admin = require("admin")


def version_from(request: Request, body_version: int | None) -> int | None:
    """Optimistické zamykání: hlavička If-Match má přednost před polem `version` v těle."""
    header = request.headers.get("if-match", "").strip().strip('"')
    if header.isdigit():
        return int(header)
    return body_version
