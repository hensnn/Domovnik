"""Štítky (PDF) a rozlišení naskenovaného kódu."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from domovnik.api import deps
from domovnik.api.deps import RequestCtx
from domovnik.errors import ValidationFailed
from domovnik.schemas import ResolveOut
from domovnik.services import labels as label_service

router = APIRouter(tags=["labels"])

PageFormat = Literal["A4_3x8", "A4_2x5", "A4_4x12"]


def _parse_ids(raw: str) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(uuid.UUID(part))
        except ValueError as exc:
            raise ValidationFailed(f"Neplatné ID „{part}“.") from exc
    return out


@router.get(
    "/labels/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "PDF se štítky (A4)"}},
)
def labels_pdf(
    kind: Literal["item", "location"],
    ids: Annotated[str, Query(description="ID oddělená čárkou (v pořadí tisku)")],
    format: PageFormat | None = None,
    start: Annotated[int, Query(ge=0, description="První použitá buňka na archu (0-based)")] = 0,
    show_path: bool | None = None,
    guides: bool | None = None,
    rc: RequestCtx = Depends(deps.read),
) -> Response:
    """Archy A4 se štítky (QR kód = `label_code`). Výchozí volby bere z nastavení `labels.*`."""
    pdf = label_service.build_pdf(
        rc.db,
        kind,
        _parse_ids(ids),
        page_format=format,
        start=start,
        show_path=show_path,
        guides=guides,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="stitky.pdf"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/resolve", response_model=ResolveOut)
def resolve(
    code: str = Query(min_length=1, max_length=200), rc: RequestCtx = Depends(deps.read)
) -> ResolveOut:
    """Převede text z QR štítku (nebo ručně zadaný kód) na věc / umístění. Nezná-li, 404."""
    return label_service.resolve_code(rc.db, code)
