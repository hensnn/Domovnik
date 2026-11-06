"""Čtení a zápis nastavení (global / per-user) s validací dle registru a šifrováním tajemství."""

from __future__ import annotations

import base64
import hashlib
import uuid
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from domovnik.config import get_settings
from domovnik.context import ActorContext
from domovnik.db.models import Setting
from domovnik.errors import Forbidden, NotFound, ValidationFailed
from domovnik.services.common import emit
from domovnik.settings_registry import GROUPS, REGISTRY, SettingDef

SECRET_MASK = "********"


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValidationFailed("Tajnou hodnotu nelze dešifrovat (změnil se secret_key?).") from exc


def _definition(key: str) -> SettingDef:
    d = REGISTRY.get(key)
    if d is None:
        raise NotFound(f"Neznámé nastavení „{key}“.")
    return d


def validate_value(d: SettingDef, value: Any) -> Any:
    """Zkontroluje typ a rozsah; vrací normalizovanou hodnotu."""

    def bad(msg: str) -> ValidationFailed:
        return ValidationFailed(f"{d.key}: {msg}")

    t = d.type
    if t in ("string", "text", "secret"):
        if not isinstance(value, str):
            raise bad("očekává se text")
        return value
    if t == "bool":
        if not isinstance(value, bool):
            raise bad("očekává se ano/ne")
        return value
    if t in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise bad("očekává se číslo")
        if t == "int" and int(value) != value:
            raise bad("očekává se celé číslo")
        num = int(value) if t == "int" else float(value)
        if d.min is not None and num < d.min:
            raise bad(f"minimum je {d.min}")
        if d.max is not None and num > d.max:
            raise bad(f"maximum je {d.max}")
        return num
    if t == "enum":
        if value not in d.choices:
            raise bad(f"povolené hodnoty: {', '.join(d.choices)}")
        return value
    if t == "string_list":
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise bad("očekává se seznam textů")
        return value
    raise bad("nepodporovaný typ")  # pragma: no cover


def _row(db: Session, key: str, user_id: uuid.UUID | None) -> Setting | None:
    stmt = select(Setting).where(Setting.key == key)
    if user_id is None:
        stmt = stmt.where(Setting.scope == "global")
    else:
        stmt = stmt.where(Setting.scope == "user", Setting.user_id == user_id)
    return db.execute(stmt).scalar_one_or_none()


def _raw_value(row: Setting, d: SettingDef) -> Any:
    if row.is_secret:
        return decrypt(row.value["enc"])
    return row.value["v"] if isinstance(row.value, dict) and "v" in row.value else row.value


def get_value(db: Session, key: str, user_id: uuid.UUID | None = None) -> Any:
    """Efektivní hodnota: uživatelská (pokud je povolena) → globální → výchozí z registru."""
    d = _definition(key)
    if user_id is not None and d.scope == "user":
        row = _row(db, key, user_id)
        if row is not None:
            return _raw_value(row, d)
    row = _row(db, key, None)
    if row is not None:
        return _raw_value(row, d)
    return d.default


def set_value(
    db: Session,
    ctx: ActorContext,
    key: str,
    value: Any,
    *,
    user_id: uuid.UUID | None = None,
    actor_is_admin: bool = False,
) -> None:
    """Nastaví globální (user_id=None, jen admin) nebo uživatelskou hodnotu."""
    d = _definition(key)
    value = validate_value(d, value)
    if user_id is None:
        if d.admin_only and not actor_is_admin:
            raise Forbidden("Toto nastavení smí měnit jen administrátor.")
    elif d.scope != "user":
        raise ValidationFailed(f"{key}: nelze nastavit per uživatel.")
    stored = {"enc": encrypt(value)} if d.is_secret else {"v": value}
    row = _row(db, key, user_id)
    if row is None:
        db.add(
            Setting(
                scope="global" if user_id is None else "user",
                user_id=user_id,
                key=key,
                value=stored,
                is_secret=d.is_secret,
                updated_by=ctx.actor_id,
            )
        )
    else:
        row.value = stored
        row.updated_by = ctx.actor_id
    db.flush()
    emit(
        db,
        ctx,
        "setting.updated",
        "setting",
        uuid.uuid5(uuid.NAMESPACE_URL, key),
        {"key": key, "user_scope": user_id is not None},
    )


def reset_value(
    db: Session,
    ctx: ActorContext,
    key: str,
    *,
    user_id: uuid.UUID | None = None,
    actor_is_admin: bool = False,
) -> None:
    d = _definition(key)
    if user_id is None and d.admin_only and not actor_is_admin:
        raise Forbidden("Toto nastavení smí měnit jen administrátor.")
    row = _row(db, key, user_id)
    if row is not None:
        db.delete(row)
        db.flush()


class SettingOut(BaseModel):
    key: str
    group: str
    group_label: str
    label: str
    description: str
    type: str
    scope: str
    choices: list[str]
    min: float | None
    max: float | None
    restart_required: bool
    admin_only: bool
    default: Any
    value: Any  # u tajných hodnot maska nebo prázdný řetězec
    is_default: bool
    has_value: bool = False  # jen pro secret


def list_effective(db: Session, user_id: uuid.UUID | None = None) -> list[SettingOut]:
    """Všechna nastavení s efektivní hodnotou (tajné maskované)."""
    global_rows = {
        r.key: r for r in db.execute(select(Setting).where(Setting.scope == "global")).scalars()
    }
    user_rows: dict[str, Setting] = {}
    if user_id is not None:
        user_rows = {
            r.key: r
            for r in db.execute(
                select(Setting).where(Setting.scope == "user", Setting.user_id == user_id)
            ).scalars()
        }
    out: list[SettingOut] = []
    for d in REGISTRY.values():
        row = (user_rows.get(d.key) if d.scope == "user" else None) or global_rows.get(d.key)
        if d.is_secret:
            has = row is not None and bool(decrypt(row.value["enc"]))
            value: Any = SECRET_MASK if has else ""
            default: Any = ""
        else:
            value = _raw_value(row, d) if row is not None else d.default
            default = d.default
            has = row is not None
        out.append(
            SettingOut(
                key=d.key,
                group=d.group,
                group_label=GROUPS.get(d.group, d.group),
                label=d.label,
                description=d.description,
                type=d.type,
                scope=d.scope,
                choices=list(d.choices),
                min=d.min,
                max=d.max,
                restart_required=d.restart_required,
                admin_only=d.admin_only,
                default=default,
                value=value,
                is_default=row is None,
                has_value=has,
            )
        )
    return out
