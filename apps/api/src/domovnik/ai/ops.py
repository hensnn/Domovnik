"""Operace „balíčku změn“: schémata, popis pro člověka, provedení a inverzní operace (undo).

Každá změna od AI prochází těmito operacemi nad běžnými službami (service layer) –
AI nemá žádnou vlastní cestu k databázi.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy.orm import Session

from domovnik.context import ActorContext
from domovnik.db.models import Category, Item, ItemPlacement, Location, User
from domovnik.errors import ValidationFailed
from domovnik.schemas import (
    CategoryCreate,
    CategoryUpdate,
    ItemCreate,
    ItemUpdate,
    KnowledgeCreate,
    LocationCreate,
    LocationUpdate,
    PlacementIn,
)
from domovnik.services import categories, items, knowledge, locations
from domovnik.services import tags as tag_service

SEP = " › "


# --- Schémata operací ---------------------------------------------------------------------


class _Op(BaseModel):
    model_config = {"extra": "forbid"}


class CreateItemOp(_Op):
    op: Literal["create_item"]
    name: str = Field(min_length=1)
    category_id: uuid.UUID | None = None
    category_path: list[str] | None = Field(default=None, description="např. ['Nářadí','Ruční']")
    location_id: uuid.UUID | None = None
    location_path: list[str] | None = Field(default=None, description="např. ['Dům','Garáž']")
    unplaced: bool = Field(
        default=False,
        description="true jen když uživatel výslovně chce věc BEZ umístění",
    )
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    notes: str | None = None
    description: str | None = None
    brand: str | None = None
    model: str | None = None
    serial_no: str | None = None
    ean: str | None = None
    is_consumable: bool = False
    unit: str = "ks"
    status: Literal["stored", "in_use", "lent", "repair", "discarded", "sold", "lost"] = "stored"


class UpdateItemOp(_Op):
    op: Literal["update_item"]
    item_id: uuid.UUID
    name: str | None = None
    notes: str | None = None
    description: str | None = None
    brand: str | None = None
    model: str | None = None
    status: Literal["stored", "in_use", "lent", "repair", "discarded", "sold", "lost"] | None = None
    category_id: uuid.UUID | None = None
    category_path: list[str] | None = None
    aliases: list[str] | None = None
    tags: list[str] | None = Field(default=None, description="nahradí všechny tagy")
    add_tags: list[str] | None = None
    remove_tags: list[str] | None = None


class MoveItemOp(_Op):
    op: Literal["move_item"]
    item_id: uuid.UUID
    to_location_id: uuid.UUID | None = None
    to_location_path: list[str] | None = None
    from_location_id: uuid.UUID | None = None
    quantity: Decimal | None = Field(default=None, gt=0)


class SetQuantityOp(_Op):
    op: Literal["set_quantity"]
    item_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal = Field(ge=0)


class DeleteItemOp(_Op):
    op: Literal["delete_item"]
    item_id: uuid.UUID


class CreateLocationOp(_Op):
    op: Literal["create_location"]
    name: str = Field(min_length=1)
    parent_id: uuid.UUID | None = None
    parent_path: list[str] | None = None
    kind: Literal[
        "building", "floor", "room", "zone", "furniture", "shelf", "drawer", "box", "other"
    ] = "other"
    is_movable: bool = False
    notes: str | None = None


class UpdateLocationOp(_Op):
    op: Literal["update_location"]
    location_id: uuid.UUID
    name: str | None = None
    kind: (
        Literal["building", "floor", "room", "zone", "furniture", "shelf", "drawer", "box", "other"]
        | None
    ) = None
    notes: str | None = None
    description: str | None = None


class MoveLocationOp(_Op):
    op: Literal["move_location"]
    location_id: uuid.UUID
    new_parent_id: uuid.UUID | None = None
    new_parent_path: list[str] | None = None
    to_root: bool = False


class ArchiveLocationOp(_Op):
    op: Literal["archive_location"]
    location_id: uuid.UUID


class CreateCategoryOp(_Op):
    op: Literal["create_category"]
    name: str = Field(min_length=1)
    parent_id: uuid.UUID | None = None
    parent_path: list[str] | None = None
    description: str | None = None


class UpdateCategoryOp(_Op):
    op: Literal["update_category"]
    category_id: uuid.UUID
    name: str | None = None
    description: str | None = None
    new_parent_id: uuid.UUID | None = None
    new_parent_path: list[str] | None = None
    to_root: bool = False


class MergeCategoriesOp(_Op):
    op: Literal["merge_categories"]
    source_id: uuid.UUID
    target_id: uuid.UUID


class DeleteCategoryOp(_Op):
    op: Literal["delete_category"]
    category_id: uuid.UUID
    reassign_to: uuid.UUID | None = None


class AddTagOp(_Op):
    op: Literal["add_tag"]
    item_id: uuid.UUID
    tag: str


class RemoveTagOp(_Op):
    op: Literal["remove_tag"]
    item_id: uuid.UUID
    tag: str


class AddKnowledgeOp(_Op):
    op: Literal["add_knowledge"]
    title: str = Field(min_length=1, max_length=200, description="krátký název pravidla / znalosti")
    content: str = Field(min_length=1, max_length=2000, description="znění pravidla, srozumitelně")
    topic: Literal["household", "rules", "naming", "other"] = "other"


# jen pro inverzní operace (undo) – AI je navrhovat nesmí
class DeleteKnowledgeOp(_Op):
    op: Literal["delete_knowledge"]
    knowledge_id: uuid.UUID


class RestoreItemOp(_Op):
    op: Literal["restore_item"]
    item_id: uuid.UUID


class RemoveFromLocationOp(_Op):
    op: Literal["remove_from_location"]
    item_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal | None = None


class DeleteLocationOp(_Op):
    op: Literal["delete_location"]
    location_id: uuid.UUID


class UnarchiveLocationOp(_Op):
    op: Literal["unarchive_location"]
    location_id: uuid.UUID


ProposableOp = Annotated[
    CreateItemOp
    | UpdateItemOp
    | MoveItemOp
    | SetQuantityOp
    | DeleteItemOp
    | CreateLocationOp
    | UpdateLocationOp
    | MoveLocationOp
    | ArchiveLocationOp
    | CreateCategoryOp
    | UpdateCategoryOp
    | MergeCategoriesOp
    | DeleteCategoryOp
    | AddTagOp
    | RemoveTagOp
    | AddKnowledgeOp,
    Field(discriminator="op"),
]
AnyOp = Annotated[
    CreateItemOp
    | UpdateItemOp
    | MoveItemOp
    | SetQuantityOp
    | DeleteItemOp
    | CreateLocationOp
    | UpdateLocationOp
    | MoveLocationOp
    | ArchiveLocationOp
    | CreateCategoryOp
    | UpdateCategoryOp
    | MergeCategoriesOp
    | DeleteCategoryOp
    | AddTagOp
    | RemoveTagOp
    | RestoreItemOp
    | RemoveFromLocationOp
    | DeleteLocationOp
    | UnarchiveLocationOp
    | AddKnowledgeOp
    | DeleteKnowledgeOp,
    Field(discriminator="op"),
]
PROPOSABLE = TypeAdapter(ProposableOp)
ANY_OP = TypeAdapter(AnyOp)

# Operace s větším dopadem: vyžadují potvrzení i při vyšší důvěře
RISKY = {
    "delete_item",
    "merge_categories",
    "delete_category",
    "archive_location",
    "move_location",
    "add_knowledge",
}
# Operace, které AI nikdy nesmí provést bez potvrzení v UI (ani v hlasovém režimu).
# `add_knowledge` patří sem, protože uložený text se vkládá do promptu při každém dotazu.
NEVER_AUTO = {"delete_item", "delete_category", "merge_categories", "add_knowledge"}


def parse_op(data: dict[str, Any], *, internal: bool = False) -> Any:
    try:
        return (ANY_OP if internal else PROPOSABLE).validate_python(data)
    except Exception as exc:  # pydantic.ValidationError, zpráva je pro model srozumitelná
        raise ValidationFailed(f"Neplatná operace: {exc}") from exc


# --- Pomocné vyhledávání ------------------------------------------------------------------


def _find_location(db: Session, path: list[str]) -> Location | None:
    parent_id: uuid.UUID | None = None
    found: Location | None = None
    for name in path:
        candidates = [
            x
            for x in db.query(Location).filter(Location.archived_at.is_(None)).all()
            if x.parent_id == parent_id and x.name.lower() == name.strip().lower()
        ]
        if not candidates:
            return None
        found = candidates[0]
        parent_id = found.id
    return found


def _find_category(db: Session, path: list[str]) -> Category | None:
    parent_id: uuid.UUID | None = None
    found: Category | None = None
    for name in path:
        candidates = [
            x
            for x in db.query(Category).all()
            if x.parent_id == parent_id and x.name.lower() == name.strip().lower()
        ]
        if not candidates:
            return None
        found = candidates[0]
        parent_id = found.id
    return found


def _loc_name(db: Session, loc_id: uuid.UUID | None) -> str:
    if loc_id is None:
        return "nejvyšší úroveň"
    return locations.location_full_names(db, [loc_id]).get(loc_id, str(loc_id))


def _target_location_text(db: Session, loc_id: uuid.UUID | None, path: list[str] | None) -> str:
    if loc_id:
        return f"„{_loc_name(db, loc_id)}“"
    if path:
        existing = _find_location(db, path)
        return f"„{SEP.join(path)}“" + ("" if existing else " (nové umístění)")
    return "?"


def _target_category_text(db: Session, cat_id: uuid.UUID | None, path: list[str] | None) -> str:
    if cat_id:
        cat = db.get(Category, cat_id)
        return f"„{cat.name if cat else cat_id}“"
    if path:
        existing = _find_category(db, path)
        return f"„{SEP.join(path)}“" + ("" if existing else " (nová kategorie)")
    return "?"


def _item_name(db: Session, item_id: uuid.UUID) -> str:
    item = db.get(Item, item_id)
    return f"„{item.name}“" if item else f"({item_id})"


def _resolve_location(
    db: Session, ctx: ActorContext, loc_id: uuid.UUID | None, path: list[str] | None
) -> uuid.UUID:
    if loc_id:
        return loc_id
    if path:
        return locations.get_or_create_path(db, ctx, path).id
    raise ValidationFailed("Chybí umístění (location_id nebo cesta).")


def _resolve_category(
    db: Session, ctx: ActorContext, cat_id: uuid.UUID | None, path: list[str] | None
) -> uuid.UUID | None:
    if cat_id:
        return cat_id
    if path:
        return categories.get_or_create_path(db, ctx, path).id
    return None


# --- Popis operace pro člověka (náhled před potvrzením) ------------------------------------


def describe(db: Session, op: BaseModel) -> str:
    match op:
        case CreateItemOp():
            parts = [f"Vytvořit věc „{op.name}“"]
            if op.quantity != 1:
                parts.append(f"{op.quantity} {op.unit}")
            if op.category_id or op.category_path:
                parts.append(
                    f"kategorie {_target_category_text(db, op.category_id, op.category_path)}"
                )
            if op.location_id or op.location_path:
                parts.append(f"do {_target_location_text(db, op.location_id, op.location_path)}")
            return ", ".join(parts)
        case UpdateItemOp():
            changes = [
                k
                for k in (
                    "name",
                    "notes",
                    "description",
                    "brand",
                    "model",
                    "status",
                    "aliases",
                    "tags",
                    "add_tags",
                    "remove_tags",
                )
                if getattr(op, k) is not None
            ]
            if op.category_id or op.category_path:
                changes.append(
                    f"kategorie → {_target_category_text(db, op.category_id, op.category_path)}"
                )
            return f"Upravit {_item_name(db, op.item_id)}: " + ", ".join(changes or ["beze změny"])
        case MoveItemOp():
            qty = f"{op.quantity} ks " if op.quantity else ""
            return (
                f"Přesunout {qty}{_item_name(db, op.item_id)} do "
                f"{_target_location_text(db, op.to_location_id, op.to_location_path)}"
            )
        case SetQuantityOp():
            return (
                f"Nastavit množství {_item_name(db, op.item_id)} na {op.quantity} "
                f"v {_target_location_text(db, op.location_id, None)}"
            )
        case DeleteItemOp():
            return f"Smazat (do koše) {_item_name(db, op.item_id)}"
        case CreateLocationOp():
            parent = (
                f" v {_target_location_text(db, op.parent_id, op.parent_path)}"
                if op.parent_id or op.parent_path
                else ""
            )
            return f"Vytvořit umístění „{op.name}“{parent}"
        case UpdateLocationOp():
            return f"Upravit umístění „{_loc_name(db, op.location_id)}“"
        case MoveLocationOp():
            target = (
                "nejvyšší úroveň"
                if op.to_root
                else _target_location_text(db, op.new_parent_id, op.new_parent_path)
            )
            return f"Přesunout umístění „{_loc_name(db, op.location_id)}“ do {target}"
        case ArchiveLocationOp():
            return f"Archivovat umístění „{_loc_name(db, op.location_id)}“"
        case CreateCategoryOp():
            parent = (
                f" pod {_target_category_text(db, op.parent_id, op.parent_path)}"
                if op.parent_id or op.parent_path
                else ""
            )
            return f"Vytvořit kategorii „{op.name}“{parent}"
        case UpdateCategoryOp():
            cat_u = db.get(Category, op.category_id)
            return f"Upravit kategorii „{cat_u.name if cat_u else op.category_id}“"
        case MergeCategoriesOp():
            s, t = db.get(Category, op.source_id), db.get(Category, op.target_id)
            return (
                f"Sloučit kategorii „{s.name if s else op.source_id}“ do "
                f"„{t.name if t else op.target_id}“"
            )
        case DeleteCategoryOp():
            cat_d = db.get(Category, op.category_id)
            return f"Smazat kategorii „{cat_d.name if cat_d else op.category_id}“"
        case AddTagOp():
            return f"Přidat tag „{op.tag}“ k {_item_name(db, op.item_id)}"
        case RemoveTagOp():
            return f"Odebrat tag „{op.tag}“ z {_item_name(db, op.item_id)}"
        case RestoreItemOp():
            return f"Obnovit {_item_name(db, op.item_id)}"
        case AddKnowledgeOp():
            return f"Uložit do knihovny znalostí: „{op.title}“ – {op.content[:160]}"
        case DeleteKnowledgeOp():
            return "Odebrat záznam z knihovny znalostí"
        case _:
            return op.__class__.__name__


# --- Provedení ----------------------------------------------------------------------------


def _inverse(op: str, **payload: Any) -> dict[str, Any]:
    return {
        "op": op,
        **{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in payload.items()},
    }


def execute(
    db: Session, ctx: ActorContext, op: BaseModel
) -> tuple[uuid.UUID | None, dict[str, Any] | None]:
    """Provede operaci. Vrací (id dotčené entity, inverzní operace nebo None = nelze vrátit)."""
    match op:
        case CreateItemOp():
            cat_id = _resolve_category(db, ctx, op.category_id, op.category_path)
            placements = []
            if op.location_id or op.location_path:
                loc_id = _resolve_location(db, ctx, op.location_id, op.location_path)
                placements = [PlacementIn(location_id=loc_id, quantity=op.quantity)]
            item = items.create_item(
                db,
                ctx,
                ItemCreate(
                    name=op.name,
                    category_id=cat_id,
                    tags=op.tags,
                    aliases=op.aliases,
                    notes=op.notes,
                    description=op.description,
                    brand=op.brand,
                    model=op.model,
                    serial_no=op.serial_no,
                    ean=op.ean,
                    is_consumable=op.is_consumable,
                    unit=op.unit,
                    status=op.status,
                    placements=placements,
                ),
            )
            return item.id, _inverse("delete_item", item_id=item.id)

        case UpdateItemOp():
            item = items.get_item(db, op.item_id)
            cat_id = _resolve_category(db, ctx, op.category_id, op.category_path)
            previous: dict[str, Any] = {}
            patch: dict[str, Any] = {}
            for field in ("name", "notes", "description", "brand", "model", "status", "aliases"):
                value = getattr(op, field)
                if value is not None:
                    prev_value = getattr(item, field)
                    # None nelze v operaci vyjádřit → u textů se vrací prázdný řetězec (= vymazat)
                    previous[field] = "" if prev_value is None else prev_value
                    patch[field] = value
            if cat_id is not None:
                previous["category_id"] = item.category_id
                patch["category_id"] = cat_id
            old_tags = tag_service.item_tag_names(db, item.id)
            new_tags: list[str] | None = None
            if op.tags is not None:
                new_tags = op.tags
            elif op.add_tags or op.remove_tags:
                drop = {t.lower() for t in (op.remove_tags or [])}
                new_tags = [t for t in [*old_tags, *(op.add_tags or [])] if t.lower() not in drop]
            if new_tags is not None:
                patch["tags"] = new_tags
                previous["tags"] = old_tags
            items.update_item(db, ctx, item.id, ItemUpdate.model_validate(patch))
            inv = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in previous.items()}
            return item.id, {
                "op": "update_item",
                "item_id": str(item.id),
                **inv,
                **({"category_id": inv.get("category_id")} if "category_id" in inv else {}),
            }

        case MoveItemOp():
            item = items.get_item(db, op.item_id)
            to_id = _resolve_location(db, ctx, op.to_location_id, op.to_location_path)
            before = list(db.query(ItemPlacement).filter(ItemPlacement.item_id == item.id).all())
            src = op.from_location_id
            if src is None and len(before) == 1:
                src = before[0].location_id
            moved = op.quantity or (
                next((p.quantity for p in before if p.location_id == src), Decimal(1))
            )
            items.move(
                db, ctx, item.id, to_id, from_location_id=op.from_location_id, quantity=op.quantity
            )
            if src is None:
                return item.id, _inverse(
                    "remove_from_location", item_id=item.id, location_id=to_id, quantity=str(moved)
                )
            return item.id, _inverse(
                "move_item",
                item_id=item.id,
                to_location_id=src,
                from_location_id=to_id,
                quantity=str(moved),
            )

        case SetQuantityOp():
            item = items.get_item(db, op.item_id)
            old = (
                db.query(ItemPlacement)
                .filter(
                    ItemPlacement.item_id == item.id, ItemPlacement.location_id == op.location_id
                )
                .first()
            )
            old_qty = old.quantity if old else Decimal(0)
            items.adjust_quantity(db, ctx, item.id, op.location_id, op.quantity)
            return item.id, _inverse(
                "set_quantity", item_id=item.id, location_id=op.location_id, quantity=str(old_qty)
            )

        case DeleteItemOp():
            items.delete_item(db, ctx, op.item_id)
            return op.item_id, _inverse("restore_item", item_id=op.item_id)

        case RestoreItemOp():
            items.restore_item(db, ctx, op.item_id)
            return op.item_id, _inverse("delete_item", item_id=op.item_id)

        case RemoveFromLocationOp():
            items.remove(db, ctx, op.item_id, op.location_id, op.quantity)
            return op.item_id, None

        case CreateLocationOp():
            parent = None
            if op.parent_id or op.parent_path:
                parent = _resolve_location(db, ctx, op.parent_id, op.parent_path)
            loc = locations.create_location(
                db,
                ctx,
                LocationCreate(
                    name=op.name,
                    parent_id=parent,
                    kind=op.kind,
                    is_movable=op.is_movable,
                    notes=op.notes,
                ),
            )
            return loc.id, _inverse("delete_location", location_id=loc.id)

        case DeleteLocationOp():
            locations.delete_location(db, ctx, op.location_id)
            return op.location_id, None

        case UpdateLocationOp():
            loc_u = db.get(Location, op.location_id)
            if loc_u is None:
                raise ValidationFailed("Umístění neexistuje.")
            prev = {
                k: (getattr(loc_u, k) or "")
                for k in ("name", "kind", "notes", "description")
                if getattr(op, k) is not None
            }
            locations.update_location(
                db,
                ctx,
                op.location_id,
                LocationUpdate.model_validate({k: getattr(op, k) for k in prev}),
            )
            return op.location_id, {
                "op": "update_location",
                "location_id": str(op.location_id),
                **prev,
            }

        case MoveLocationOp():
            loc_m = db.get(Location, op.location_id)
            if loc_m is None:
                raise ValidationFailed("Umístění neexistuje.")
            old_parent = loc_m.parent_id
            new_parent: uuid.UUID | None = None
            if not op.to_root:
                new_parent = _resolve_location(db, ctx, op.new_parent_id, op.new_parent_path)
            locations.move_location(db, ctx, loc_m, new_parent)
            return op.location_id, _inverse(
                "move_location",
                location_id=op.location_id,
                new_parent_id=old_parent,
                to_root=old_parent is None,
            )

        case ArchiveLocationOp():
            locations.archive_location(db, ctx, op.location_id)
            return op.location_id, _inverse("unarchive_location", location_id=op.location_id)

        case UnarchiveLocationOp():
            locations.unarchive_location(db, ctx, op.location_id)
            return op.location_id, _inverse("archive_location", location_id=op.location_id)

        case CreateCategoryOp():
            parent_cat = _resolve_category(db, ctx, op.parent_id, op.parent_path)
            cat_c = categories.create_category(
                db,
                ctx,
                CategoryCreate(name=op.name, parent_id=parent_cat, description=op.description),
            )
            return cat_c.id, _inverse("delete_category", category_id=cat_c.id)

        case UpdateCategoryOp():
            cat_u = db.get(Category, op.category_id)
            if cat_u is None:
                raise ValidationFailed("Kategorie neexistuje.")
            prev_c: dict[str, Any] = {}
            patch_c: dict[str, Any] = {}
            if op.name is not None:
                prev_c["name"], patch_c["name"] = cat_u.name, op.name
            if op.description is not None:
                prev_c["description"], patch_c["description"] = cat_u.description, op.description
            if op.to_root or op.new_parent_id or op.new_parent_path:
                new_p = (
                    None
                    if op.to_root
                    else _resolve_category(db, ctx, op.new_parent_id, op.new_parent_path)
                )
                prev_c["new_parent_id"] = str(cat_u.parent_id) if cat_u.parent_id else None
                prev_c["to_root"] = cat_u.parent_id is None
                patch_c["parent_id"] = new_p
            categories.update_category(
                db, ctx, op.category_id, CategoryUpdate.model_validate(patch_c)
            )
            return op.category_id, {
                "op": "update_category",
                "category_id": str(op.category_id),
                **prev_c,
            }

        case MergeCategoriesOp():
            categories.merge_categories(db, ctx, op.source_id, op.target_id)
            return op.target_id, None  # sloučení nelze automaticky vrátit

        case DeleteCategoryOp():
            cat_d = db.get(Category, op.category_id)
            if cat_d is None:
                raise ValidationFailed("Kategorie neexistuje.")
            used = db.query(Item).filter(Item.category_id == cat_d.id).count()
            inverse = (
                None
                if used
                else _inverse(
                    "create_category",
                    name=cat_d.name,
                    parent_id=cat_d.parent_id,
                    description=cat_d.description,
                )
            )
            categories.delete_category(db, ctx, op.category_id, reassign_to=op.reassign_to)
            return op.category_id, inverse

        case AddTagOp() | RemoveTagOp():
            item = items.get_item(db, op.item_id)
            current = tag_service.item_tag_names(db, item.id)
            has = any(t.lower() == op.tag.strip().lower() for t in current)
            adding = isinstance(op, AddTagOp)
            new = (
                [*current, op.tag]
                if adding
                else [t for t in current if t.lower() != op.tag.strip().lower()]
            )
            items.update_item(db, ctx, item.id, ItemUpdate(tags=new))
            if adding == has:  # nic se nezměnilo
                return item.id, None
            return item.id, _inverse(
                "remove_tag" if adding else "add_tag", item_id=item.id, tag=op.tag
            )

        case AddKnowledgeOp():
            # Záznam od AI zapne rovnou jen admin; od ostatních čeká na schválení v knihovně.
            actor = db.get(User, ctx.actor_id) if ctx.actor_id else None
            row = knowledge.create_entry(
                db,
                ctx,
                KnowledgeCreate(title=op.title, content=op.content, topic=op.topic),
                source="ai",
                enabled=actor is not None and actor.role == "admin",
            )
            return row.id, _inverse("delete_knowledge", knowledge_id=row.id)

        case DeleteKnowledgeOp():
            knowledge.delete_entry(db, ctx, op.knowledge_id)
            return op.knowledge_id, None

        case _:
            raise ValidationFailed(f"Nepodporovaná operace {op.__class__.__name__}.")
