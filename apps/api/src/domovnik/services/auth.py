"""Uživatelé, hesla, relace (cookie) a API tokeny."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domovnik.config import get_settings
from domovnik.context import ActorContext
from domovnik.db.models import ApiToken, AuthSession, User
from domovnik.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from domovnik.services.common import emit, flush, get_or_404

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")

ROLES = ("admin", "member", "viewer", "guest")
ALL_SCOPES = ("items:read", "items:write", "files:write", "ai:chat", "admin")
ROLE_SCOPES: dict[str, frozenset[str]] = {
    "admin": frozenset(ALL_SCOPES),
    "member": frozenset({"items:read", "items:write", "files:write", "ai:chat"}),
    "viewer": frozenset({"items:read", "ai:chat"}),
    "guest": frozenset({"items:read"}),
}
MIN_PASSWORD_LENGTH = 10


@dataclass
class Principal:
    """Přihlášený subjekt (uživatel přes relaci nebo token) a jeho efektivní oprávnění."""

    user: User
    scopes: frozenset[str]
    auth_type: str  # 'session' | 'token'
    csrf_token: str | None = None
    session_id: uuid.UUID | None = None
    token_id: uuid.UUID | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def has(self, scope: str) -> bool:
        return scope in self.scopes or "admin" in self.scopes


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# --- uživatelé ----------------------------------------------------------------------------


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationFailed(f"Heslo musí mít alespoň {MIN_PASSWORD_LENGTH} znaků.")
    return _hasher.hash(password)


def create_user(
    db: Session,
    ctx: ActorContext,
    *,
    username: str,
    display_name: str,
    password: str,
    role: str = "member",
    email: str | None = None,
) -> User:
    if role not in ROLES:
        raise ValidationFailed(f"Neznámá role „{role}“.")
    username = username.strip()
    if not username:
        raise ValidationFailed("Uživatelské jméno je prázdné.")
    user = User(
        username=username,
        display_name=display_name.strip() or username,
        email=email,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    flush(db)
    emit(db, ctx, "user.created", "user", user.id, {"username": username, "role": role})
    return user


def has_users(db: Session) -> bool:
    return db.execute(select(func.count()).select_from(User)).scalar_one() > 0


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.execute(
        select(User).where(func.lower(User.username) == username.strip().lower())
    ).scalar_one_or_none()
    if user is None or not user.password_hash:
        # vyrovná časování, ať nejde poznat existence účtu
        with suppress(VerificationError):
            _hasher.verify(_DUMMY_HASH, password)
        return None
    try:
        _hasher.verify(user.password_hash, password)
    except (VerificationError, InvalidHashError):
        return None
    if not user.is_active:
        return None
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _hasher.hash(password)
    user.last_login_at = datetime.now(UTC)
    return user


def change_password(db: Session, user: User, old: str, new: str) -> None:
    if not user.password_hash or not _verify(user.password_hash, old):
        raise Unauthorized("Stávající heslo nesouhlasí.")
    user.password_hash = hash_password(new)
    # po změně hesla zneplatnit všechny relace
    for s in db.execute(select(AuthSession).where(AuthSession.user_id == user.id)).scalars():
        db.delete(s)


def _verify(hash_: str, password: str) -> bool:
    try:
        return bool(_hasher.verify(hash_, password))
    except (VerificationError, InvalidHashError):
        return False


def set_user_active(db: Session, user_id: uuid.UUID, active: bool) -> User:
    user = get_or_404(db, User, user_id, what="Uživatel")
    if not active:
        admins = db.execute(
            select(func.count()).select_from(User).where(User.role == "admin", User.is_active)
        ).scalar_one()
        if user.role == "admin" and user.is_active and admins <= 1:
            raise Conflict("Nelze deaktivovat posledního administrátora.")
        for s in db.execute(select(AuthSession).where(AuthSession.user_id == user.id)).scalars():
            db.delete(s)
    user.is_active = active
    return user


# --- relace (cookie) ----------------------------------------------------------------------


def create_session(
    db: Session, user: User, *, user_agent: str | None = None, ip: str | None = None
) -> tuple[str, AuthSession]:
    raw = secrets.token_urlsafe(32)
    session = AuthSession(
        token_hash=_sha(raw),
        csrf_token=secrets.token_urlsafe(24),
        user_id=user.id,
        user_agent=(user_agent or "")[:300] or None,
        ip=ip,
        expires_at=datetime.now(UTC) + timedelta(hours=get_settings().session_ttl_hours),
    )
    db.add(session)
    flush(db)
    return raw, session


def resolve_session(db: Session, raw_token: str) -> Principal | None:
    s = db.execute(
        select(AuthSession).where(AuthSession.token_hash == _sha(raw_token))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if s is None or s.expires_at <= now:
        return None
    user = db.get(User, s.user_id)
    if user is None or not user.is_active:
        return None
    if now - s.last_seen_at > timedelta(minutes=5):
        s.last_seen_at = now
    return Principal(
        user=user,
        scopes=ROLE_SCOPES.get(user.role, frozenset()),
        auth_type="session",
        csrf_token=s.csrf_token,
        session_id=s.id,
    )


def delete_session(db: Session, raw_token: str) -> None:
    s = db.execute(
        select(AuthSession).where(AuthSession.token_hash == _sha(raw_token))
    ).scalar_one_or_none()
    if s is not None:
        db.delete(s)


# --- API tokeny ---------------------------------------------------------------------------

TOKEN_PREFIX = "dmv_"


def create_api_token(
    db: Session,
    ctx: ActorContext,
    user: User,
    *,
    name: str,
    scopes: list[str],
    expires_in_days: int | None = None,
) -> tuple[str, ApiToken]:
    """Vytvoří token. Holou hodnotu vrací jen tady – v DB zůstává pouze hash."""
    bad = [s for s in scopes if s not in ALL_SCOPES]
    if bad:
        raise ValidationFailed(f"Neznámé scopes: {', '.join(bad)}.")
    allowed = ROLE_SCOPES.get(user.role, frozenset())
    if not set(scopes) <= allowed and "admin" not in allowed:
        raise ValidationFailed("Token nemůže mít širší oprávnění než jeho uživatel.")
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = ApiToken(
        user_id=user.id,
        name=name.strip() or "token",
        token_hash=_sha(raw),
        scopes=sorted(set(scopes)),
        expires_at=(
            datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None
        ),
    )
    db.add(token)
    flush(db)
    emit(db, ctx, "token.created", "api_token", token.id, {"name": token.name})
    return raw, token


def resolve_token(db: Session, raw_token: str) -> Principal | None:
    t = db.execute(
        select(ApiToken).where(ApiToken.token_hash == _sha(raw_token))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if t is None or t.revoked_at is not None or (t.expires_at and t.expires_at <= now):
        return None
    user = db.get(User, t.user_id)
    if user is None or not user.is_active:
        return None
    if t.last_used_at is None or now - t.last_used_at > timedelta(minutes=1):
        t.last_used_at = now
    effective = frozenset(t.scopes) & ROLE_SCOPES.get(user.role, frozenset())
    return Principal(user=user, scopes=effective, auth_type="token", token_id=t.id)


def revoke_token(db: Session, user: User, token_id: uuid.UUID) -> None:
    t = db.get(ApiToken, token_id)
    if t is None or (t.user_id != user.id and user.role != "admin"):
        raise NotFound("Token neexistuje.")
    t.revoked_at = datetime.now(UTC)


def list_tokens(db: Session, user: User) -> list[ApiToken]:
    return list(
        db.execute(
            select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc())
        ).scalars()
    )
