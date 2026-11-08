"""ORM modely.

Sloupce spravované triggery (path, depth, version, updated_at, label_code) jsou označeny
FetchedValue – po flush je načti přes ``session.refresh(obj)``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    FetchedValue,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

FV = FetchedValue()


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _updated() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), server_onupdate=FV)


def _version() -> Mapped[int]:
    return mapped_column(Integer, server_default=text("1"), server_onupdate=FV)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, server_default="member")
    locale: Mapped[str] = mapped_column(Text, server_default="cs")
    timezone: Mapped[str] = mapped_column(Text, server_default="Europe/Prague")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = _now()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{items:read}'"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class AuthSession(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    csrf_token: Mapped[str] = mapped_column(Text)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(Text)
    value: Mapped[Any] = mapped_column(JSONB)
    is_secret: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    updated_at: Mapped[datetime] = _now()
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[uuid.UUID] = _uuid_pk()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    kind: Mapped[str] = mapped_column(Text, server_default="other")
    name: Mapped[str] = mapped_column(Text)
    label_code: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_movable: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    color: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    path: Mapped[str | None] = mapped_column(String, server_default=FV, server_onupdate=FV)
    depth: Mapped[int | None] = mapped_column(Integer, server_default=FV, server_onupdate=FV)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    version: Mapped[int] = _version()


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[uuid.UUID] = _uuid_pk()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    version: Mapped[int] = _version()


class CustomFieldDef(Base):
    __tablename__ = "custom_field_defs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    options: Mapped[Any | None] = mapped_column(JSONB)
    unit: Mapped[str | None] = mapped_column(Text)
    is_required: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, unique=True)
    color: Mapped[str | None] = mapped_column(Text)


class ItemTag(Base):
    __tablename__ = "item_tags"
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


class FileRecord(Base):
    __tablename__ = "files"
    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(Text)
    sha256: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    storage_path: Mapped[str] = mapped_column(Text)
    original_name: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exif: Mapped[Any | None] = mapped_column(JSONB)
    blurhash: Mapped[str | None] = mapped_column(Text)
    thumbs_ready: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    ocr_text: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()


class FileLink(Base):
    __tablename__ = "file_links"
    id: Mapped[uuid.UUID] = _uuid_pk()
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(Text, server_default="gallery")
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    caption: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class Item(Base):
    __tablename__ = "items"
    id: Mapped[uuid.UUID] = _uuid_pk()
    label_code: Mapped[str] = mapped_column(Text, unique=True, server_default=FV)
    name: Mapped[str] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, server_default="stored")
    is_consumable: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    unit: Mapped[str] = mapped_column(Text, server_default="ks")
    min_quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    home_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL")
    )
    brand: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    serial_no: Mapped[str | None] = mapped_column(Text)
    ean: Mapped[str | None] = mapped_column(Text)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), server_default="CZK")
    purchase_place: Mapped[str | None] = mapped_column(Text)
    warranty_until: Mapped[date | None] = mapped_column(Date)
    expires_at: Mapped[date | None] = mapped_column(Date)
    est_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    condition: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    primary_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = _updated()
    version: Mapped[int] = _version()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ItemPlacement(Base):
    __tablename__ = "item_placements"
    id: Mapped[uuid.UUID] = _uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), server_default=text("1"))
    note: Mapped[str | None] = mapped_column(Text)
    placed_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    version: Mapped[int] = _version()


class Movement(Base):
    __tablename__ = "movements"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    from_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL")
    )
    to_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL")
    )
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    moved_at: Mapped[datetime] = _now()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(Text, server_default="ui")
    change_set_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    note: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = _now()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source: Mapped[str | None] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(Text)
    before: Mapped[Any | None] = mapped_column(JSONB)
    after: Mapped[Any | None] = mapped_column(JSONB)
    change_set_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    request_id: Mapped[str | None] = mapped_column(Text)


class EventOutbox(Base):
    __tablename__ = "event_outbox"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    payload: Mapped[Any] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class AiConversation(Base):
    __tablename__ = "ai_conversations"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text, server_default="text")
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    archived: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class AiKnowledge(Base):
    """Záznam knihovny znalostí pro AI (pravidla uspořádání, zvyky domácnosti)."""

    __tablename__ = "ai_knowledge"
    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(Text, server_default="other")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    source: Mapped[str] = mapped_column(Text, server_default="admin")
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    version: Mapped[int] = _version()


class AiMessage(Base):
    __tablename__ = "ai_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[Any | None] = mapped_column(JSONB)
    tool_result: Mapped[Any | None] = mapped_column(JSONB)
    file_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default=text("'{}'"))
    model: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 5))
    created_at: Mapped[datetime] = _now()


class AiChangeSet(Base):
    __tablename__ = "ai_change_sets"
    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="proposed")
    auto_applied: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = _now()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiChangeOp(Base):
    __tablename__ = "ai_change_ops"
    id: Mapped[uuid.UUID] = _uuid_pk()
    change_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_change_sets.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    op: Mapped[str] = mapped_column(Text)
    payload: Mapped[Any] = mapped_column(JSONB)
    inverse: Mapped[Any | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    result_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class PhotoAnalysis(Base):
    __tablename__ = "photo_analyses"
    id: Mapped[uuid.UUID] = _uuid_pk()
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    context_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL")
    )
    user_hint: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    result: Mapped[Any | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 5))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PhotoDetection(Base):
    __tablename__ = "photo_detections"
    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("photo_analyses.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(Text)
    bbox: Mapped[Any | None] = mapped_column(JSONB)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    suggested: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    suggested_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL")
    )
    suggestion_reason: Mapped[str | None] = mapped_column(Text)
    matched_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("items.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InventorySession(Base):
    __tablename__ = "inventory_sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="open")
    started_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = _now()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InventoryLine(Base):
    __tablename__ = "inventory_lines"
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), primary_key=True
    )
    expected_qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    counted_qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    result: Mapped[str] = mapped_column(Text, server_default="unchecked")
    counted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
