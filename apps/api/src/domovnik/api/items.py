"""Věci: seznam/hledání, CRUD, přesuny, množství, hromadné operace."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response

from domovnik.api import deps
from domovnik.api.deps import RequestCtx
from domovnik.errors import DomainError
from domovnik.schemas import (
    AdjustRequest,
    BulkRequest,
    BulkResult,
    ItemCreate,
    ItemOut,
    ItemPageOut,
    ItemStatus,
    ItemUpdate,
    MovementOut,
    MoveRequest,
    PlacementIn,
    RemoveRequest,
)
from domovnik.services import items as item_service
from domovnik.services import search as search_service
from domovnik.services import settings as settings_service
from domovnik.services.search import ItemFilter, SortKey

router = APIRouter(tags=["items"])


@router.get("/items", response_model=ItemPageOut)
def list_items(
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    status: ItemStatus | None = None,
    tag: list[str] = Query(default_factory=list),
    unplaced: bool | None = None,
    low_stock: bool | None = None,
    consumable: bool | None = None,
    owner_id: uuid.UUID | None = None,
    warranty_before: date | None = None,
    expires_before: date | None = None,
    trash: bool = False,
    sort: SortKey = "relevance",
    desc: bool = False,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    rc: RequestCtx = Depends(deps.read),
) -> ItemPageOut:
    """Seznam a hledání věcí. Filtry se kombinují (AND); kategorie a umístění zahrnují podstrom."""
    threshold = float(settings_service.get_value(rc.db, "search.fuzzy_threshold"))
    page = search_service.search_items(
        rc.db,
        ItemFilter(
            q=q,
            category_id=category_id,
            location_id=location_id,
            status=status,
            tags=tag,
            unplaced=unplaced,
            low_stock=low_stock,
            consumable=consumable,
            owner_id=owner_id,
            warranty_before=warranty_before,
            expires_before=expires_before,
            trash=trash,
            sort=sort,
            descending=desc,
            limit=limit,
            offset=offset,
            fuzzy_threshold=threshold,
        ),
    )
    return ItemPageOut(items=page.items, total=page.total, limit=page.limit, offset=page.offset)


@router.post("/items", response_model=ItemOut, status_code=201)
def create_item(
    body: ItemCreate, response: Response, rc: RequestCtx = Depends(deps.write)
) -> ItemOut:
    item = item_service.create_item(rc.db, rc.ctx, body)
    rc.commit()
    out = item_service.get_item_out(rc.db, item.id)
    response.headers["Location"] = f"/api/v1/items/{item.id}"
    return out


@router.get("/items/duplicates", response_model=list[ItemOut])
def duplicates(name: str, rc: RequestCtx = Depends(deps.read)) -> list[ItemOut]:
    """Věci s velmi podobným názvem (kontrola před založením)."""
    found = search_service.find_duplicates(rc.db, name)
    return item_service.to_out(rc.db, found)


@router.post("/items/bulk", response_model=BulkResult)
def bulk(body: BulkRequest, rc: RequestCtx = Depends(deps.write)) -> BulkResult:
    """Hromadná operace; každá věc se zpracuje zvlášť (chyba jedné nezablokuje ostatní)."""
    ok, failed = 0, []
    for item_id in body.ids:
        try:
            with rc.db.begin_nested():
                _bulk_one(rc, body, item_id)
            ok += 1
        except DomainError as exc:
            failed.append({"id": str(item_id), "error": exc.message})
    rc.commit()
    return BulkResult(ok=ok, failed=failed)


def _bulk_one(rc: RequestCtx, body: BulkRequest, item_id: uuid.UUID) -> None:
    db, ctx = rc.db, rc.ctx
    if body.action == "move":
        if body.location_id is None:
            raise DomainError("Chybí cílové umístění.")
        item_service.move(db, ctx, item_id, body.location_id)
    elif body.action == "set_category":
        item_service.update_item(
            db, ctx, item_id, ItemUpdate.model_validate({"category_id": body.category_id})
        )
    elif body.action == "set_status":
        if body.status is None:
            raise DomainError("Chybí stav.")
        item_service.update_item(db, ctx, item_id, ItemUpdate(status=body.status))
    elif body.action in ("add_tags", "remove_tags"):
        current = item_service.get_item_out(db, item_id).tags
        lowered = {t.lower() for t in body.tags}
        new = (
            [*current, *body.tags]
            if body.action == "add_tags"
            else [t for t in current if t.lower() not in lowered]
        )
        item_service.update_item(db, ctx, item_id, ItemUpdate(tags=new))
    elif body.action == "delete":
        item_service.delete_item(db, ctx, item_id)


@router.get("/items/{item_id}", response_model=ItemOut)
def get_item(
    item_id: uuid.UUID, response: Response, rc: RequestCtx = Depends(deps.read)
) -> ItemOut:
    out = item_service.get_item_out(rc.db, item_id, include_deleted=True)
    response.headers["ETag"] = f'"{out.version}"'
    return out


@router.patch("/items/{item_id}", response_model=ItemOut)
def update_item(
    item_id: uuid.UUID, body: ItemUpdate, request: Request, rc: RequestCtx = Depends(deps.write)
) -> ItemOut:
    body.version = deps.version_from(request, body.version)
    item_service.update_item(rc.db, rc.ctx, item_id, body)
    rc.commit()
    return item_service.get_item_out(rc.db, item_id)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: uuid.UUID, rc: RequestCtx = Depends(deps.write)) -> None:
    """Přesune věc do koše."""
    item_service.delete_item(rc.db, rc.ctx, item_id)
    rc.commit()


@router.post("/items/{item_id}/restore", response_model=ItemOut)
def restore_item(item_id: uuid.UUID, rc: RequestCtx = Depends(deps.write)) -> ItemOut:
    item_service.restore_item(rc.db, rc.ctx, item_id)
    rc.commit()
    return item_service.get_item_out(rc.db, item_id)


@router.delete("/items/{item_id}/purge", status_code=204)
def purge_item(item_id: uuid.UUID, rc: RequestCtx = Depends(deps.write)) -> None:
    """Trvalé smazání – jen z koše."""
    item_service.purge_item(rc.db, rc.ctx, item_id)
    rc.commit()


@router.post("/items/{item_id}/place", response_model=ItemOut)
def place_item(
    item_id: uuid.UUID, body: PlacementIn, rc: RequestCtx = Depends(deps.write)
) -> ItemOut:
    item_service.place(rc.db, rc.ctx, item_id, body.location_id, body.quantity, note=body.note)
    rc.commit()
    return item_service.get_item_out(rc.db, item_id)


@router.post("/items/{item_id}/move", response_model=ItemOut)
def move_item(
    item_id: uuid.UUID, body: MoveRequest, rc: RequestCtx = Depends(deps.write)
) -> ItemOut:
    item_service.move(
        rc.db,
        rc.ctx,
        item_id,
        body.to_location_id,
        from_location_id=body.from_location_id,
        quantity=body.quantity,
        note=body.note,
    )
    rc.commit()
    return item_service.get_item_out(rc.db, item_id)


@router.post("/items/{item_id}/adjust", response_model=ItemOut)
def adjust_item(
    item_id: uuid.UUID, body: AdjustRequest, rc: RequestCtx = Depends(deps.write)
) -> ItemOut:
    item_service.adjust_quantity(
        rc.db, rc.ctx, item_id, body.location_id, body.quantity, note=body.note
    )
    rc.commit()
    return item_service.get_item_out(rc.db, item_id)


@router.post("/items/{item_id}/remove", response_model=ItemOut)
def remove_item(
    item_id: uuid.UUID, body: RemoveRequest, rc: RequestCtx = Depends(deps.write)
) -> ItemOut:
    item_service.remove(
        rc.db,
        rc.ctx,
        item_id,
        body.location_id,
        body.quantity,
        dispose=body.dispose,
        note=body.note,
    )
    rc.commit()
    return item_service.get_item_out(rc.db, item_id)


@router.get("/items/{item_id}/movements", response_model=list[MovementOut])
def item_movements(
    item_id: uuid.UUID, limit: int = Query(100, ge=1, le=1000), rc: RequestCtx = Depends(deps.read)
) -> list[Any]:
    return item_service.list_movements(rc.db, item_id, limit=limit)


@router.get("/movements", response_model=list[MovementOut])
def movements(
    limit: int = Query(50, ge=1, le=1000), rc: RequestCtx = Depends(deps.read)
) -> list[Any]:
    return item_service.list_movements(rc.db, limit=limit)
