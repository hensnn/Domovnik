"""Pydantic schémata sdílená službami a API."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

LocationKind = Literal[
    "building", "floor", "room", "zone", "furniture", "shelf", "drawer", "box", "other"
]
ItemStatus = Literal["stored", "in_use", "lent", "repair", "discarded", "sold", "lost"]
Condition = Literal["new", "good", "worn", "broken"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Umístění -----------------------------------------------------------------------------


class LocationCreate(BaseModel):
    id: uuid.UUID | None = None  # klient může zvolit ID (offline zápis); opakování je idempotentní
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    kind: LocationKind = "other"
    label_code: str | None = Field(default=None, max_length=64)
    description: str | None = None
    notes: str | None = None
    is_movable: bool = False
    color: str | None = None
    icon: str | None = None
    sort_order: int = 0
    attributes: dict[str, Any] = Field(default_factory=dict)


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    kind: LocationKind | None = None
    description: str | None = None
    notes: str | None = None
    is_movable: bool | None = None
    color: str | None = None
    icon: str | None = None
    sort_order: int | None = None
    attributes: dict[str, Any] | None = None
    version: int | None = None  # optimistické zamykání


class LocationOut(ORM):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    kind: str
    name: str
    label_code: str
    description: str | None
    notes: str | None
    is_movable: bool
    color: str | None
    icon: str | None
    sort_order: int
    attributes: dict[str, Any]
    depth: int | None
    archived_at: datetime | None
    version: int
    full_name: str | None = None
    item_count: int = 0  # položky v tomto umístění včetně podstromu
    direct_item_count: int = 0


# --- Kategorie ----------------------------------------------------------------------------


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    description: str | None = None
    color: str | None = None
    icon: str | None = None
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    description: str | None = None
    color: str | None = None
    icon: str | None = None
    sort_order: int | None = None
    version: int | None = None


class CategoryOut(ORM):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    slug: str
    description: str | None
    color: str | None
    icon: str | None
    sort_order: int
    version: int
    item_count: int = 0  # včetně podkategorií
    direct_item_count: int = 0
    full_name: str | None = None


# --- Věci ---------------------------------------------------------------------------------


class PlacementIn(BaseModel):
    location_id: uuid.UUID
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    note: str | None = None


class ItemFields(BaseModel):
    """Společná pole pro vytvoření i úpravu věci."""

    name: str = Field(min_length=1, max_length=300)
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    notes: str | None = None
    category_id: uuid.UUID | None = None
    status: ItemStatus = "stored"
    is_consumable: bool = False
    unit: str = "ks"
    min_quantity: Decimal | None = Field(default=None, ge=0)
    home_location_id: uuid.UUID | None = None
    brand: str | None = None
    model: str | None = None
    serial_no: str | None = None
    ean: str | None = None
    purchase_date: date | None = None
    purchase_price: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="CZK", min_length=3, max_length=3)
    purchase_place: str | None = None
    warranty_until: date | None = None
    expires_at: date | None = None
    est_value: Decimal | None = Field(default=None, ge=0)
    condition: Condition | None = None
    owner_id: uuid.UUID | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ItemCreate(ItemFields):
    id: uuid.UUID | None = None  # klient může zvolit ID (offline zápis); opakování je idempotentní
    tags: list[str] = Field(default_factory=list)
    placements: list[PlacementIn] = Field(default_factory=list)


class ItemUpdate(BaseModel):
    """Částečná úprava – mění se jen pole, která klient skutečně poslal."""

    name: str | None = Field(default=None, min_length=1, max_length=300)
    aliases: list[str] | None = None
    description: str | None = None
    notes: str | None = None
    category_id: uuid.UUID | None = None
    status: ItemStatus | None = None
    is_consumable: bool | None = None
    unit: str | None = None
    min_quantity: Decimal | None = None
    home_location_id: uuid.UUID | None = None
    brand: str | None = None
    model: str | None = None
    serial_no: str | None = None
    ean: str | None = None
    purchase_date: date | None = None
    purchase_price: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    purchase_place: str | None = None
    warranty_until: date | None = None
    expires_at: date | None = None
    est_value: Decimal | None = None
    condition: Condition | None = None
    owner_id: uuid.UUID | None = None
    attributes: dict[str, Any] | None = None
    tags: list[str] | None = None
    version: int | None = None


class PlacementOut(BaseModel):
    location_id: uuid.UUID
    quantity: Decimal
    note: str | None = None
    location_label: str | None = None
    location_path: str | None = None


class ItemOut(ORM):
    id: uuid.UUID
    label_code: str
    name: str
    aliases: list[str]
    description: str | None
    notes: str | None
    category_id: uuid.UUID | None
    category_path: str | None = None
    status: str
    is_consumable: bool
    unit: str
    min_quantity: Decimal | None
    home_location_id: uuid.UUID | None
    brand: str | None
    model: str | None
    serial_no: str | None
    ean: str | None
    purchase_date: date | None
    purchase_price: Decimal | None
    currency: str
    purchase_place: str | None
    warranty_until: date | None
    expires_at: date | None
    est_value: Decimal | None
    condition: str | None
    owner_id: uuid.UUID | None
    attributes: dict[str, Any]
    primary_file_id: uuid.UUID | None
    file_count: int = 0  # počet připojených souborů (fotky + dokumenty)
    created_at: datetime
    updated_at: datetime
    version: int
    deleted_at: datetime | None
    tags: list[str] = Field(default_factory=list)
    placements: list[PlacementOut] = Field(default_factory=list)
    total_quantity: Decimal = Decimal(0)
    is_low_stock: bool = False


class MoveRequest(BaseModel):
    from_location_id: uuid.UUID | None = None
    to_location_id: uuid.UUID
    quantity: Decimal | None = Field(default=None, gt=0)
    note: str | None = None


class AdjustRequest(BaseModel):
    location_id: uuid.UUID
    quantity: Decimal = Field(ge=0)
    note: str | None = None


class RemoveRequest(BaseModel):
    location_id: uuid.UUID
    quantity: Decimal | None = Field(default=None, gt=0)
    dispose: bool = False
    note: str | None = None


class MovementOut(ORM):
    id: int
    item_id: uuid.UUID
    kind: str
    from_location_id: uuid.UUID | None
    to_location_id: uuid.UUID | None
    quantity: Decimal | None
    moved_at: datetime
    actor_id: uuid.UUID | None
    source: str
    note: str | None


class TagOut(ORM):
    id: uuid.UUID
    name: str
    color: str | None
    item_count: int = 0


# --- Uživatelé, relace, tokeny ------------------------------------------------------------


class UserOut(ORM):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    role: str
    locale: str
    timezone: str
    is_active: bool
    last_login_at: datetime | None


class SetupIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=100)
    password: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(max_length=200)


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=100)
    password: str = Field(max_length=200)
    role: Literal["admin", "member", "viewer", "guest"] = "member"
    email: str | None = None


class UserPatch(BaseModel):
    display_name: str | None = None
    email: str | None = None
    role: Literal["admin", "member", "viewer", "guest"] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, max_length=200)
    locale: str | None = None
    timezone: str | None = None


class MeOut(BaseModel):
    user: UserOut
    scopes: list[str]
    csrf_token: str | None


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["items:read"])
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class TokenOut(ORM):
    id: uuid.UUID
    name: str
    scopes: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class TokenCreated(TokenOut):
    token: str  # holá hodnota se zobrazí jen jednou


# --- Ostatní ------------------------------------------------------------------------------


class SettingUpdate(BaseModel):
    value: Any
    scope: Literal["global", "user"] = "user"


class CategoryMerge(BaseModel):
    target_id: uuid.UUID


class TagRename(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class BulkRequest(BaseModel):
    """Hromadná operace nad více věcmi."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    action: Literal["move", "set_category", "add_tags", "remove_tags", "set_status", "delete"]
    location_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    tags: list[str] = Field(default_factory=list)
    status: ItemStatus | None = None


class BulkResult(BaseModel):
    ok: int
    failed: list[dict[str, Any]] = Field(default_factory=list)


class ItemPageOut(BaseModel):
    items: list[ItemOut]
    total: int
    limit: int
    offset: int


class SearchOut(BaseModel):
    items: list[ItemOut]
    locations: list[LocationOut]
    categories: list[CategoryOut]
    totals: dict[str, int] = Field(default_factory=dict)  # počty všech nálezů před ořezem


class AuditOut(ORM):
    id: int
    at: datetime
    actor_id: uuid.UUID | None
    source: str | None
    entity_type: str
    entity_id: uuid.UUID
    action: str
    before: Any | None
    after: Any | None
    change_set_id: uuid.UUID | None


# --- Soubory (fotky, dokumenty) -----------------------------------------------------------

FileRole = Literal["primary", "gallery", "manual", "receipt", "warranty", "other"]


class FileOut(BaseModel):
    """Soubor v úložišti. Obsah: ``url`` (originál / dokument), ``thumb_*_url`` (jen fotky)."""

    id: uuid.UUID
    kind: Literal["photo", "document"]
    mime: str
    size_bytes: int
    width: int | None
    height: int | None
    original_name: str | None
    caption: str | None
    taken_at: datetime | None
    exif: dict[str, Any] | None
    blurhash: str | None
    thumbs_ready: bool
    created_at: datetime
    url: str
    thumb_256_url: str | None
    thumb_1024_url: str | None


class FileLinkOut(BaseModel):
    """Vazba souboru na věc nebo umístění; ``caption`` je popisek vazby (jinak popisek souboru)."""

    id: uuid.UUID
    item_id: uuid.UUID | None
    location_id: uuid.UUID | None
    role: FileRole
    is_primary: bool
    sort_order: int
    caption: str | None
    created_at: datetime
    file: FileOut


class UploadOut(BaseModel):
    file: FileOut
    link: FileLinkOut | None = None
    duplicate: bool = False  # stejný obsah už v úložišti byl – nic se neuložilo podruhé


class BatchUploadEntry(BaseModel):
    filename: str | None
    ok: bool
    error: str | None = None
    upload: UploadOut | None = None


class BatchUploadOut(BaseModel):
    results: list[BatchUploadEntry]
    ok: int
    failed: int


class FileLinkPatch(BaseModel):
    """Částečná úprava vazby – mění se jen pole, která klient poslal."""

    role: FileRole | None = None
    caption: str | None = None
    sort_order: int | None = Field(default=None, ge=0)
    is_primary: bool | None = None  # True = nastavit jako primární


class FileOrder(BaseModel):
    """Nové pořadí vazeb (ID vazeb od prvního). Nevyjmenované vazby zůstanou za nimi."""

    link_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


# --- Štítky a skenování ---------------------------------------------------------------------


class ResolveOut(BaseModel):
    """Výsledek rozlišení naskenovaného kódu."""

    type: Literal["item", "location"]
    id: uuid.UUID
    name: str
    label_code: str
    full_name: str | None = None  # umístění: celá cesta; věc: cesta jejího (prvního) umístění
    deleted: bool = False  # věc v koši / archivované umístění


# --- Inventura ------------------------------------------------------------------------------

InventoryResult = Literal["unchecked", "ok", "missing", "extra", "moved"]
InventoryStatus = Literal["open", "closed", "cancelled"]


class InventoryStart(BaseModel):
    location_id: uuid.UUID | None = None  # rozsah (podstrom); None = celý dům
    name: str | None = Field(default=None, max_length=200)


class InventoryCounts(BaseModel):
    total: int = 0
    unchecked: int = 0
    ok: int = 0
    missing: int = 0
    extra: int = 0
    moved: int = 0
    changes: int = 0  # kolik řádků by uzavření s aplikací změnilo v datech


class InventorySessionOut(BaseModel):
    id: uuid.UUID
    location_id: uuid.UUID | None
    location_name: str | None = None
    name: str
    status: InventoryStatus
    started_by: uuid.UUID | None
    started_at: datetime
    closed_at: datetime | None
    applied_at: datetime | None
    counts: InventoryCounts = Field(default_factory=InventoryCounts)


class InventoryLineOut(BaseModel):
    item_id: uuid.UUID
    item_name: str
    item_label_code: str
    unit: str
    location_id: uuid.UUID
    location_name: str | None = None
    location_path: str | None = None
    expected_qty: Decimal | None
    counted_qty: Decimal | None
    result: InventoryResult
    counted_at: datetime | None
    diff: Decimal | None = None  # counted − expected (None, dokud se nepočítalo)


class InventorySessionDetail(InventorySessionOut):
    lines: list[InventoryLineOut] = Field(default_factory=list)


class InventoryCountIn(BaseModel):
    """Spočtené množství; ``null`` vrátí řádek do stavu „nezkontrolováno“."""

    counted_qty: Decimal | None = Field(default=None, ge=0)


class InventoryCloseIn(BaseModel):
    apply: bool = False  # True = rozdíly zapsat do dat (množství, last_seen_at)


class InventoryChange(BaseModel):
    item_id: uuid.UUID
    item_name: str
    location_id: uuid.UUID
    from_qty: Decimal
    to_qty: Decimal


class InventoryCloseOut(BaseModel):
    session: InventorySessionOut
    applied: bool
    changes: list[InventoryChange] = Field(default_factory=list)
