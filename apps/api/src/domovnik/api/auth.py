"""Přihlášení, úvodní nastavení, uživatelé a API tokeny."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from domovnik.api import deps
from domovnik.api.deps import SESSION_COOKIE, RequestCtx
from domovnik.config import get_settings
from domovnik.context import SYSTEM, bind_context
from domovnik.db.models import User
from domovnik.errors import Conflict, Forbidden, NotFound, Unauthorized
from domovnik.ratelimit import login_limiter
from domovnik.schemas import (
    LoginIn,
    MeOut,
    PasswordChange,
    SetupIn,
    TokenCreate,
    TokenCreated,
    TokenOut,
    UserCreate,
    UserOut,
    UserPatch,
)
from domovnik.services import auth as auth_service

router = APIRouter(tags=["auth"])


def _set_cookie(response: Response, raw: str) -> None:
    s = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        raw,
        max_age=s.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=s.cookie_secure,
        path="/",
    )


def _me(principal: auth_service.Principal) -> MeOut:
    return MeOut(
        user=UserOut.model_validate(principal.user),
        scopes=sorted(principal.scopes),
        csrf_token=principal.csrf_token,
    )


@router.get("/auth/status")
def status(request: Request, db: Session = Depends(deps.get_db)) -> dict[str, Any]:
    """Veřejné: je potřeba úvodní nastavení? Jsem přihlášen?"""
    authenticated = False
    try:
        deps.get_principal(request, db)
        authenticated = True
    except (Unauthorized, Forbidden):
        pass
    return {"setup_required": not auth_service.has_users(db), "authenticated": authenticated}


@router.post("/auth/setup", response_model=MeOut, status_code=201)
def setup(
    body: SetupIn, request: Request, response: Response, db: Session = Depends(deps.get_db)
) -> MeOut:
    """Vytvoří prvního uživatele (administrátora). Funguje jen, dokud žádný neexistuje."""
    db.execute(select(User.id).limit(1))
    if auth_service.has_users(db):
        raise Conflict("Úvodní nastavení už proběhlo.")
    bind_context(db, SYSTEM)
    user = auth_service.create_user(
        db,
        SYSTEM,
        username=body.username,
        display_name=body.display_name or body.username,
        password=body.password,
        role="admin",
    )
    raw, session = auth_service.create_session(
        db, user, user_agent=request.headers.get("user-agent"), ip=_ip(request)
    )
    db.commit()
    _set_cookie(response, raw)
    return MeOut(
        user=UserOut.model_validate(user),
        scopes=sorted(auth_service.ROLE_SCOPES["admin"]),
        csrf_token=session.csrf_token,
    )


def _ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)


@router.post("/auth/login", response_model=MeOut)
def login(
    body: LoginIn, request: Request, response: Response, db: Session = Depends(deps.get_db)
) -> MeOut:
    key = f"{_ip(request)}|{body.username.lower()}"
    login_limiter.check(key)
    user = auth_service.authenticate(db, body.username, body.password)
    if user is None:
        login_limiter.fail(key)
        raise Unauthorized("Nesprávné jméno nebo heslo.")
    login_limiter.reset(key)
    raw, session = auth_service.create_session(
        db, user, user_agent=request.headers.get("user-agent"), ip=_ip(request)
    )
    db.commit()
    _set_cookie(response, raw)
    return MeOut(
        user=UserOut.model_validate(user),
        scopes=sorted(auth_service.ROLE_SCOPES.get(user.role, frozenset())),
        csrf_token=session.csrf_token,
    )


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(deps.get_db),
) -> None:
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        # CSRF kontrola přes get_principal (odhlášení je změna stavu)
        deps.get_principal(request, db)
        auth_service.delete_session(db, raw)
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/auth/me", response_model=MeOut)
def me(principal: auth_service.Principal = Depends(deps.get_principal)) -> MeOut:
    return _me(principal)


@router.post("/auth/password", status_code=204)
def change_password(body: PasswordChange, rc: RequestCtx = Depends(deps.own)) -> None:
    auth_service.change_password(rc.db, rc.principal.user, body.old_password, body.new_password)
    rc.commit()


# --- API tokeny (každý spravuje své) -------------------------------------------------------


@router.get("/tokens", response_model=list[TokenOut])
def list_tokens(rc: RequestCtx = Depends(deps.own)) -> list[Any]:
    return auth_service.list_tokens(rc.db, rc.principal.user)


@router.post("/tokens", response_model=TokenCreated, status_code=201)
def create_token(body: TokenCreate, rc: RequestCtx = Depends(deps.own)) -> TokenCreated:
    raw, tok = auth_service.create_api_token(
        rc.db,
        rc.ctx,
        rc.principal.user,
        name=body.name,
        scopes=body.scopes,
        expires_in_days=body.expires_in_days,
    )
    rc.commit()
    return TokenCreated(**TokenOut.model_validate(tok).model_dump(), token=raw)


@router.delete("/tokens/{token_id}", status_code=204)
def revoke_token(token_id: uuid.UUID, rc: RequestCtx = Depends(deps.own)) -> None:
    auth_service.revoke_token(rc.db, rc.principal.user, token_id)
    rc.commit()


# --- Správa uživatelů (admin) -------------------------------------------------------------


@router.get("/users", response_model=list[UserOut])
def list_users(rc: RequestCtx = Depends(deps.admin)) -> list[User]:
    return list(rc.db.execute(select(User).order_by(User.username)).scalars())


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, rc: RequestCtx = Depends(deps.admin)) -> User:
    user = auth_service.create_user(
        rc.db,
        rc.ctx,
        username=body.username,
        display_name=body.display_name or body.username,
        password=body.password,
        role=body.role,
        email=body.email,
    )
    rc.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(user_id: uuid.UUID, body: UserPatch, rc: RequestCtx = Depends(deps.admin)) -> User:
    user = rc.db.get(User, user_id)
    if user is None:
        raise NotFound("Uživatel neexistuje.")
    data = body.model_dump(exclude_unset=True)
    if "role" in data and data["role"] != "admin" and user.role == "admin":
        admins = (
            rc.db.execute(select(User).where(User.role == "admin", User.is_active)).scalars().all()
        )
        if len(admins) <= 1:
            raise Conflict("Nelze odebrat roli poslednímu administrátorovi.")
    if "password" in data and data["password"]:
        user.password_hash = auth_service.hash_password(data.pop("password"))
    data.pop("password", None)
    active = data.pop("is_active", None)
    for key, value in data.items():
        if value is not None:
            setattr(user, key, value)
    if active is not None:
        auth_service.set_user_active(rc.db, user.id, active)
    rc.commit()
    return user
