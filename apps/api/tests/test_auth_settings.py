"""Testy autentizace, tokenů a registru nastavení."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.db.models import AuthSession, Setting
from domovnik.errors import Conflict, Forbidden, NotFound, ValidationFailed
from domovnik.services import auth, settings
from domovnik.settings_registry import REGISTRY


def mk(db: Session, ctx: ActorContext, name: str = "anna", role: str = "member"):  # type: ignore[no-untyped-def]
    return auth.create_user(
        db,
        ctx,
        username=name,
        display_name=name.title(),
        password="correct horse battery",
        role=role,
    )


def test_password_policy_and_login(db: Session, ctx: ActorContext) -> None:
    with pytest.raises(ValidationFailed):
        auth.create_user(db, ctx, username="x", display_name="X", password="short")
    u = mk(db, ctx)
    assert u.password_hash and "correct" not in u.password_hash
    assert auth.authenticate(db, "anna", "correct horse battery") is not None
    assert auth.authenticate(db, "ANNA", "correct horse battery") is not None  # citext
    assert auth.authenticate(db, "anna", "wrong password!!") is None
    assert auth.authenticate(db, "nobody", "whatever password") is None
    u.is_active = False
    db.flush()
    assert auth.authenticate(db, "anna", "correct horse battery") is None


def test_session_lifecycle(db: Session, ctx: ActorContext) -> None:
    u = mk(db, ctx)
    raw, sess = auth.create_session(db, u, user_agent="pytest", ip="127.0.0.1")
    assert raw not in sess.token_hash  # v DB je jen hash
    principal = auth.resolve_session(db, raw)
    assert principal is not None and principal.user.id == u.id
    assert principal.has("items:write") and not principal.has("admin")
    assert principal.csrf_token == sess.csrf_token

    assert auth.resolve_session(db, "neexistuje") is None
    sess.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()
    assert auth.resolve_session(db, raw) is None

    raw2, _ = auth.create_session(db, u)
    auth.delete_session(db, raw2)
    db.flush()
    assert auth.resolve_session(db, raw2) is None


def test_change_password_invalidates_sessions(db: Session, ctx: ActorContext) -> None:
    u = mk(db, ctx)
    raw, _ = auth.create_session(db, u)
    auth.change_password(db, u, "correct horse battery", "another long password")
    db.flush()
    assert auth.resolve_session(db, raw) is None
    assert auth.authenticate(db, "anna", "another long password") is not None
    assert db.execute(select(AuthSession)).first() is None


def test_api_tokens_scopes_and_expiry(db: Session, ctx: ActorContext) -> None:
    viewer = mk(db, ctx, "viewer1", "viewer")
    with pytest.raises(ValidationFailed):  # token nesmí být silnější než uživatel
        auth.create_api_token(db, ctx, viewer, name="x", scopes=["items:write"])
    with pytest.raises(ValidationFailed):
        auth.create_api_token(db, ctx, viewer, name="x", scopes=["nonsense"])

    member = mk(db, ctx, "member1", "member")
    raw, tok = auth.create_api_token(
        db, ctx, member, name="HA", scopes=["items:read"], expires_in_days=1
    )
    assert raw.startswith("dmv_") and raw not in tok.token_hash
    p = auth.resolve_token(db, raw)
    assert p is not None and p.scopes == frozenset({"items:read"}) and not p.has("items:write")

    tok.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.flush()
    assert auth.resolve_token(db, raw) is None
    tok.expires_at = None
    auth.revoke_token(db, member, tok.id)
    db.flush()
    assert auth.resolve_token(db, raw) is None
    with pytest.raises(NotFound):
        auth.revoke_token(db, viewer, tok.id)  # cizí token


def test_cannot_deactivate_last_admin(db: Session, ctx: ActorContext) -> None:
    admin = mk(db, ctx, "boss", "admin")
    # v testovací DB existuje navíc fixture `user` s rolí admin → deaktivujme ji nejdřív
    db.execute(text("UPDATE users SET is_active = false WHERE username = 'tester'"))
    with pytest.raises(Conflict):
        auth.set_user_active(db, admin.id, False)


# --- nastavení ----------------------------------------------------------------------------


def test_registry_is_consistent() -> None:
    assert len(REGISTRY) >= 60
    for d in REGISTRY.values():
        settings.validate_value(d, d.default) if not d.is_secret else None
        if d.type == "enum":
            assert d.default in d.choices or d.default == ""


def test_setting_defaults_global_and_user_override(db: Session, ctx: ActorContext, user) -> None:  # type: ignore[no-untyped-def]
    assert settings.get_value(db, "ui.theme") == "auto"
    settings.set_value(db, ctx, "ui.theme", "dark", user_id=user.id)
    assert settings.get_value(db, "ui.theme", user.id) == "dark"
    assert settings.get_value(db, "ui.theme") == "auto"  # globální beze změny
    settings.set_value(db, ctx, "items.trash_retention_days", 30, actor_is_admin=True)
    assert settings.get_value(db, "items.trash_retention_days", user.id) == 30
    settings.reset_value(db, ctx, "ui.theme", user_id=user.id)
    assert settings.get_value(db, "ui.theme", user.id) == "auto"


def test_setting_validation_and_permissions(db: Session, ctx: ActorContext, user) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationFailed):
        settings.set_value(db, ctx, "ui.theme", "neon", user_id=user.id)
    with pytest.raises(ValidationFailed):
        settings.set_value(db, ctx, "photos.jpeg_quality", 5, actor_is_admin=True)
    with pytest.raises(ValidationFailed):
        settings.set_value(db, ctx, "items.require_category", "ano", actor_is_admin=True)
    with pytest.raises(Forbidden):
        settings.set_value(db, ctx, "items.trash_retention_days", 10)  # ne-admin, globální
    with pytest.raises(ValidationFailed):
        settings.set_value(
            db, ctx, "items.trash_retention_days", 10, user_id=user.id
        )  # není per-user
    with pytest.raises(NotFound):
        settings.get_value(db, "nope.nope")


def test_secrets_encrypted_and_masked(db: Session, ctx: ActorContext) -> None:
    settings.set_value(db, ctx, "ai.gemini_api_key", "AIza-super-secret", actor_is_admin=True)
    raw = db.execute(select(Setting).where(Setting.key == "ai.gemini_api_key")).scalar_one()
    assert raw.is_secret and "AIza" not in str(raw.value)
    assert settings.get_value(db, "ai.gemini_api_key") == "AIza-super-secret"
    listing = {s.key: s for s in settings.list_effective(db)}
    assert listing["ai.gemini_api_key"].value == settings.SECRET_MASK
    assert listing["ai.gemini_api_key"].has_value
    assert listing["ai.anthropic_api_key"].value == ""
    assert "AIza" not in listing["ai.gemini_api_key"].model_dump_json()
