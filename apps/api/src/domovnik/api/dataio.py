"""Import a export dat (CSV)."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile

from domovnik.api import deps
from domovnik.api.deps import RequestCtx
from domovnik.errors import PayloadTooLarge, ValidationFailed
from domovnik.schemas import ItemStatus
from domovnik.services import dataio
from domovnik.services import settings as settings_service
from domovnik.services.search import ItemFilter, SortKey, search_items

router = APIRouter(prefix="/data", tags=["data"])
MAX_IMPORT_BYTES = 10 * 1024 * 1024


@router.get("/export.csv")
def export_csv(
    columns: str | None = Query(
        None, description="Klíče sloupců oddělené čárkou (viz /data/columns)"
    ),
    per_placement: bool = True,
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    status: ItemStatus | None = None,
    tag: list[str] = Query(default_factory=list),
    unplaced: bool | None = None,
    low_stock: bool | None = None,
    sort: SortKey = "name",
    rc: RequestCtx = Depends(deps.read),
) -> Response:
    """Export věcí do CSV (české výchozí nastavení pro Excel: `;`, UTF-8 s BOM, desetinná čárka)."""
    page = search_items(
        rc.db,
        ItemFilter(
            q=q,
            category_id=category_id,
            location_id=location_id,
            status=status,
            tags=tag,
            unplaced=unplaced,
            low_stock=low_stock,
            sort=sort,
            limit=500,
            offset=0,
            fuzzy_threshold=float(settings_service.get_value(rc.db, "search.fuzzy_threshold")),
        ),
    )
    rows = list(page.items)
    offset = len(rows)
    while offset < page.total:  # po stránkách, ať se nenačte všechno najednou do ORM
        more = search_items(
            rc.db,
            ItemFilter(
                q=q,
                category_id=category_id,
                location_id=location_id,
                status=status,
                tags=tag,
                unplaced=unplaced,
                low_stock=low_stock,
                sort=sort,
                limit=500,
                offset=offset,
            ),
        )
        if not more.items:
            break
        rows.extend(more.items)
        offset += len(more.items)
    data = dataio.export_csv(
        rc.db, rows, columns=columns.split(",") if columns else None, per_placement=per_placement
    )
    name = f"domovnik-export-{date.today().isoformat()}.csv"
    return Response(
        data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/columns")
def columns(_: RequestCtx = Depends(deps.read)) -> dict[str, str]:
    """Dostupné sloupce exportu / cílová pole importu (klíč → záhlaví)."""
    return dataio.EXPORT_COLUMNS


@router.post("/import")
def import_csv(
    file: UploadFile = File(description="CSV (UTF-8 nebo Windows-1250)"),
    dry_run: bool = Form(True),
    on_duplicate: str = Form("skip"),
    mapping: str | None = Form(
        None, description='JSON {"záhlaví v CSV": "pole"}; bez něj automaticky'
    ),
    delimiter: str | None = Form(None),
    rc: RequestCtx = Depends(deps.write),
) -> dict[str, Any]:
    """Import věcí. Výchozí je zkušební běh (`dry_run=true`) s reportem po řádcích; teprve
    `dry_run=false` data opravdu uloží."""
    data = file.file.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise PayloadTooLarge("CSV je příliš velké (max. 10 MB).")
    parsed_mapping: dict[str, str] | None = None
    if mapping:
        try:
            parsed_mapping = json.loads(mapping)
        except ValueError as exc:
            raise ValidationFailed("Mapování není platný JSON.") from exc
        if not isinstance(parsed_mapping, dict):
            raise ValidationFailed("Mapování musí být objekt.")
    report = dataio.import_csv(
        rc.db,
        rc.ctx,
        data,
        mapping=parsed_mapping,
        dry_run=dry_run,
        on_duplicate=on_duplicate,
        delimiter=delimiter,
    )
    if not dry_run:
        rc.commit()
    return asdict(report)
