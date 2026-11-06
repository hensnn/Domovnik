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
