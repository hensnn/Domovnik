"""Soubory: nahrání (fotky, PDF), stažení originálu a náhledů, vazby na věci a umístění."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

from domovnik.api import deps
from domovnik.api.deps import RequestCtx
from domovnik.db.models import FileRecord
from domovnik.errors import DomainError, NotFound, PayloadTooLarge, ValidationFailed
from domovnik.schemas import (
    BatchUploadEntry,
    BatchUploadOut,
    FileLinkOut,
    FileLinkPatch,
    FileOrder,
    UploadOut,
)
from domovnik.services import files as file_service
from domovnik.services import settings as settings_service

router = APIRouter(tags=["files"])

# Obsah je adresovaný hashem a nikdy se nemění → agresivní (ale soukromá) cache v prohlížeči.
CACHE_CONTROL = "private, max-age=31536000, immutable"


# --- nahrání ------------------------------------------------------------------------------


def _read_upload(rc: RequestCtx, upload: UploadFile) -> bytes:
    """Přečte nahraný soubor nejvýš do limitu (+1 bajt, aby šlo poznat překročení)."""
    limit = file_service.max_upload_bytes(rc.db)
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise PayloadTooLarge(
            f"Soubor je příliš velký (limit {limit // 1024 // 1024} MB).", max_bytes=limit
        )
    return data


def _upload_out(result: file_service.UploadResult) -> UploadOut:
    link = file_service.link_out(result.link, result.file) if result.link else None
    return UploadOut(
        file=file_service.file_out(result.file), link=link, duplicate=not result.created
    )


@router.post("/files", response_model=UploadOut, status_code=201)
def upload_file(
    response: Response,
    file: UploadFile = File(description="Obrázek (JPEG, PNG, WebP, HEIC, GIF) nebo PDF."),
    item_id: uuid.UUID | None = Form(default=None),
    location_id: uuid.UUID | None = Form(default=None),
    role: str | None = Form(default=None),
    caption: str | None = Form(default=None),
    rc: RequestCtx = Depends(deps.files_write),
) -> UploadOut:
    """Nahraje soubor (typ se určuje z obsahu) a volitelně ho připojí k věci / umístění.

    Stejný obsah se neuloží podruhé: vrátí se existující soubor s `duplicate=true` (HTTP 200).
    """
    data = _read_upload(rc, file)
    result = file_service.upload(
        rc.db,
        rc.ctx,
        data,
        file.filename,
        item_id=item_id,
        location_id=location_id,
        role=role,
        caption=caption,
    )
    rc.commit()
    if not result.created:
        response.status_code = 200
    response.headers["Location"] = f"/api/v1/files/{result.file.id}"
    return _upload_out(result)


@router.post("/files/batch", response_model=BatchUploadOut)
def upload_files(
    files: list[UploadFile] = File(description="Více souborů najednou."),
    item_id: uuid.UUID | None = Form(default=None),
    location_id: uuid.UUID | None = Form(default=None),
    role: str | None = Form(default=None),
    caption: str | None = Form(default=None),
    rc: RequestCtx = Depends(deps.files_write),
) -> BatchUploadOut:
    """Hromadné nahrání; každý soubor se zpracuje zvlášť (chyba jednoho neblokuje ostatní)."""
    max_files = int(settings_service.get_value(rc.db, "photos.max_batch_files"))
    if len(files) > max_files:
        raise ValidationFailed(f"Najednou lze nahrát nejvýš {max_files} souborů.")
    results: list[BatchUploadEntry] = []
    for upload in files:
        try:
            data = _read_upload(rc, upload)
            with rc.db.begin_nested():
                result = file_service.upload(
                    rc.db,
                    rc.ctx,
                    data,
                    upload.filename,
                    item_id=item_id,
                    location_id=location_id,
                    role=role,
                    caption=caption,
                )
            results.append(
                BatchUploadEntry(filename=upload.filename, ok=True, upload=_upload_out(result))
            )
        except DomainError as exc:
            results.append(BatchUploadEntry(filename=upload.filename, ok=False, error=exc.message))
    rc.commit()
    ok = sum(1 for r in results if r.ok)
    return BatchUploadOut(results=results, ok=ok, failed=len(results) - ok)


# --- stažení ------------------------------------------------------------------------------


def _etag_matches(request: Request, etag: str) -> bool:
    header = request.headers.get("if-none-match", "")
    if not header:
        return False
    candidates = {part.strip().removeprefix("W/") for part in header.split(",")}
    return "*" in candidates or etag in candidates


def _serve(
    request: Request,
    path: Path,
    *,
    etag: str,
    media_type: str,
    filename: str,
    attachment: bool,
    sandbox: bool = True,
) -> Response:
    headers = {
        "ETag": etag,
        "Cache-Control": CACHE_CONTROL,
        "X-Content-Type-Options": "nosniff",
    }
    if sandbox:  # soubor se nikdy nesmí chovat jako aktivní stránka
        headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    if _etag_matches(request, etag):
        return Response(status_code=304, headers=headers)
    if not path.is_file():
        raise NotFound("Soubor chybí v úložišti.")
    return FileResponse(
        path,
        media_type=media_type,
        headers=headers,
        filename=filename,
        content_disposition_type="attachment" if attachment else "inline",
    )


@router.get("/files/{file_id}", response_class=FileResponse)
def download_file(
    file_id: uuid.UUID,
    request: Request,
    download: bool | None = None,
    rc: RequestCtx = Depends(deps.read),
) -> Response:
    """Uložený soubor (u fotek po re-enkódování). PDF se ve výchozím stavu stahuje (`attachment`);
    `download=false` ho zobrazí přímo, `download=true` vynutí stažení i u obrázků."""
    rec = file_service.get_file(rc.db, file_id)
    attachment = download if download is not None else rec.kind == "document"
    return _serve(
        request,
        file_service.main_path(rec),
        etag=f'"{rec.sha256.hex()}"',
        media_type=rec.mime,
        filename=file_service.download_name(rec),
        attachment=attachment,
        sandbox=not (rec.kind == "document" and not attachment),
    )


@router.get("/files/{file_id}/thumb", response_class=FileResponse)
def download_thumb(
    file_id: uuid.UUID,
    request: Request,
    size: int = Query(
        256,
        description="Delší strana náhledu v px: 256 nebo 1024.",
        json_schema_extra={"enum": [256, 1024]},
    ),
    rc: RequestCtx = Depends(deps.read),
) -> Response:
    """Náhled fotky (WebP, delší strana 256 nebo 1024 px). Chybějící náhled se dogeneruje."""
    rec: FileRecord = file_service.get_file(rc.db, file_id)
    if rec.kind != "photo":
        raise NotFound("Dokument nemá náhled.")
    if file_service.ensure_thumbs(rc.db, rec):
        rc.commit()
    return _serve(
        request,
        file_service.thumb_path(rec, size),
        etag=f'"{rec.sha256.hex()}-{size}"',
        media_type="image/webp",
        filename=f"{Path(file_service.download_name(rec)).stem}_{size}.webp",
        attachment=False,
    )


# --- vazby na věci a umístění --------------------------------------------------------------


@router.get("/items/{item_id}/files", response_model=list[FileLinkOut])
def item_files(item_id: uuid.UUID, rc: RequestCtx = Depends(deps.read)) -> list[FileLinkOut]:
    """Soubory věci; primární fotka první."""
    return file_service.list_for_item(rc.db, item_id)


@router.get("/locations/{location_id}/files", response_model=list[FileLinkOut])
def location_files(
    location_id: uuid.UUID, rc: RequestCtx = Depends(deps.read)
) -> list[FileLinkOut]:
    return file_service.list_for_location(rc.db, location_id)


@router.put("/items/{item_id}/files/order", response_model=list[FileLinkOut])
def reorder_item_files(
    item_id: uuid.UUID, body: FileOrder, rc: RequestCtx = Depends(deps.files_write)
) -> list[FileLinkOut]:
    file_service.reorder(rc.db, rc.ctx, body.link_ids, item_id=item_id)
    rc.commit()
    return file_service.list_for_item(rc.db, item_id)


@router.put("/locations/{location_id}/files/order", response_model=list[FileLinkOut])
def reorder_location_files(
    location_id: uuid.UUID, body: FileOrder, rc: RequestCtx = Depends(deps.files_write)
) -> list[FileLinkOut]:
    file_service.reorder(rc.db, rc.ctx, body.link_ids, location_id=location_id)
    rc.commit()
    return file_service.list_for_location(rc.db, location_id)


@router.patch("/file-links/{link_id}", response_model=FileLinkOut)
def update_file_link(
    link_id: uuid.UUID, body: FileLinkPatch, rc: RequestCtx = Depends(deps.files_write)
) -> FileLinkOut:
    """Role, popisek, pořadí; `is_primary=true` nastaví primární fotku."""
    file_service.update_link(rc.db, rc.ctx, link_id, body.model_dump(exclude_unset=True))
    rc.commit()
    return file_service.link_out_by_id(rc.db, link_id)


@router.delete("/file-links/{link_id}", status_code=204)
def delete_file_link(link_id: uuid.UUID, rc: RequestCtx = Depends(deps.files_write)) -> None:
    """Odpojí soubor od věci / umístění (soubor v úložišti zůstává)."""
    file_service.detach(rc.db, rc.ctx, link_id)
    rc.commit()


@router.delete("/files/{file_id}", status_code=204)
def delete_file(
    file_id: uuid.UUID, force: bool = False, rc: RequestCtx = Depends(deps.files_write)
) -> None:
    """Smaže soubor. Je-li připojen, vrátí 409; s `force=true` ho nejdřív odpojí."""
    file_service.delete_file(rc.db, rc.ctx, file_id, detach_links=force)
    rc.commit()
    file_service.run_pending_deletes(rc.db)
