"""Umístění, kategorie a tagy."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from domovnik.api import deps
from domovnik.api.deps import RequestCtx
from domovnik.schemas import (
    CategoryCreate,
    CategoryMerge,
    CategoryOut,
    CategoryUpdate,
    LocationCreate,
    LocationOut,
    LocationUpdate,
    TagCreate,
    TagMerge,
    TagOut,
    TagUpdate,
)
from domovnik.services import categories as category_service
from domovnik.services import locations as location_service
from domovnik.services import tags as tag_service

router = APIRouter(tags=["catalog"])


# --- Umístění -----------------------------------------------------------------------------


@router.get("/locations", response_model=list[LocationOut])
def list_locations(
    include_archived: bool = False, rc: RequestCtx = Depends(deps.read)
) -> list[LocationOut]:
    """Plochý seznam seřazený podle cesty; strom si složí klient přes `parent_id`."""
    return location_service.list_locations(rc.db, include_archived=include_archived)


@router.post("/locations", response_model=LocationOut, status_code=201)
def create_location(body: LocationCreate, rc: RequestCtx = Depends(deps.write)) -> LocationOut:
    loc = location_service.create_location(rc.db, rc.ctx, body)
    rc.commit()
    return location_service.get_location_out(rc.db, loc.id)


@router.get("/locations/{location_id}", response_model=LocationOut)
def get_location(
    location_id: uuid.UUID, response: Response, rc: RequestCtx = Depends(deps.read)
) -> LocationOut:
    out = location_service.get_location_out(rc.db, location_id)
    response.headers["ETag"] = f'"{out.version}"'
    return out


@router.patch("/locations/{location_id}", response_model=LocationOut)
def update_location(
    location_id: uuid.UUID,
    body: LocationUpdate,
    request: Request,
    rc: RequestCtx = Depends(deps.write),
) -> LocationOut:
    body.version = deps.version_from(request, body.version)
    location_service.update_location(rc.db, rc.ctx, location_id, body)
    rc.commit()
    return location_service.get_location_out(rc.db, location_id)


@router.post("/locations/{location_id}/archive", response_model=LocationOut)
def archive_location(location_id: uuid.UUID, rc: RequestCtx = Depends(deps.write)) -> LocationOut:
    location_service.archive_location(rc.db, rc.ctx, location_id)
    rc.commit()
    return location_service.get_location_out(rc.db, location_id)


@router.post("/locations/{location_id}/unarchive", response_model=LocationOut)
def unarchive_location(location_id: uuid.UUID, rc: RequestCtx = Depends(deps.write)) -> LocationOut:
    location_service.unarchive_location(rc.db, rc.ctx, location_id)
    rc.commit()
    return location_service.get_location_out(rc.db, location_id)


@router.delete("/locations/{location_id}", status_code=204)
def delete_location(location_id: uuid.UUID, rc: RequestCtx = Depends(deps.write)) -> None:
    location_service.delete_location(rc.db, rc.ctx, location_id)
    rc.commit()


@router.get("/locations/{location_id}/contents")
def location_contents(
    location_id: uuid.UUID, recursive: bool = True, rc: RequestCtx = Depends(deps.read)
) -> list[dict[str, Any]]:
    return location_service.contents(rc.db, location_id, recursive=recursive)


# --- Kategorie ----------------------------------------------------------------------------


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(rc: RequestCtx = Depends(deps.read)) -> list[CategoryOut]:
    return category_service.list_categories(rc.db)


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryCreate, rc: RequestCtx = Depends(deps.write)) -> CategoryOut:
    cat = category_service.create_category(rc.db, rc.ctx, body)
    rc.commit()
    return _category_out(rc, cat.id)


def _category_out(rc: RequestCtx, category_id: uuid.UUID) -> CategoryOut:
    return next(c for c in category_service.list_categories(rc.db) if c.id == category_id)


@router.patch("/categories/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: uuid.UUID,
    body: CategoryUpdate,
    request: Request,
    rc: RequestCtx = Depends(deps.write),
) -> CategoryOut:
    body.version = deps.version_from(request, body.version)
    category_service.update_category(rc.db, rc.ctx, category_id, body)
    rc.commit()
    return _category_out(rc, category_id)


@router.post("/categories/{category_id}/merge", response_model=CategoryOut)
def merge_category(
    category_id: uuid.UUID, body: CategoryMerge, rc: RequestCtx = Depends(deps.write)
) -> CategoryOut:
    """Sloučí kategorii `category_id` do `target_id` (věci i podkategorie se přesunou)."""
    target = category_service.merge_categories(rc.db, rc.ctx, category_id, body.target_id)
    rc.commit()
    return _category_out(rc, target.id)


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(
    category_id: uuid.UUID,
    reassign_to: uuid.UUID | None = None,
    rc: RequestCtx = Depends(deps.write),
) -> None:
    category_service.delete_category(rc.db, rc.ctx, category_id, reassign_to=reassign_to)
    rc.commit()


# --- Tagy ---------------------------------------------------------------------------------


@router.get("/tags", response_model=list[TagOut])
def list_tags(rc: RequestCtx = Depends(deps.read)) -> list[TagOut]:
    return tag_service.list_tags(rc.db)


def _tag_out(rc: RequestCtx, tag_id: uuid.UUID) -> TagOut:
    return next(t for t in tag_service.list_tags(rc.db) if t.id == tag_id)


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(body: TagCreate, rc: RequestCtx = Depends(deps.write)) -> TagOut:
    tag = tag_service.create_tag(rc.db, rc.ctx, body.name, body.color)
    rc.commit()
    return _tag_out(rc, tag.id)


@router.patch("/tags/{tag_id}", response_model=TagOut)
def update_tag(tag_id: uuid.UUID, body: TagUpdate, rc: RequestCtx = Depends(deps.write)) -> TagOut:
    """Přejmenuje tag a / nebo změní barvu (`color: null` ji odstraní)."""
    tag = tag_service.update_tag(
        rc.db,
        rc.ctx,
        tag_id,
        name=body.name,
        color=body.color,
        set_color="color" in body.model_fields_set,
    )
    rc.commit()
    return _tag_out(rc, tag.id)


@router.post("/tags/{tag_id}/merge", response_model=TagOut)
def merge_tag(tag_id: uuid.UUID, body: TagMerge, rc: RequestCtx = Depends(deps.write)) -> TagOut:
    """Sloučí tag do cílového: věci dostanou cílový tag, zdrojový se smaže."""
    target = tag_service.merge_tags(rc.db, rc.ctx, tag_id, body.target_id)
    rc.commit()
    return _tag_out(rc, target.id)


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: uuid.UUID, rc: RequestCtx = Depends(deps.write)) -> None:
    tag_service.delete_tag(rc.db, rc.ctx, tag_id)
    rc.commit()
