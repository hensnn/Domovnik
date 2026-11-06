"""Čtení fotek AI: pipeline, duplicity, návrh umístění, revize (commit), ořezy, plán, HTTP."""

from __future__ import annotations

import io
import json
import time
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.orm import Session

from domovnik.ai import changesets, vision
from domovnik.ai.providers import override_provider
from domovnik.ai.providers.base import ProviderError
from domovnik.ai.providers.fake import DEMO_DETECTIONS, FakeProvider, text
from domovnik.config import get_settings
from domovnik.context import ActorContext
from domovnik.db.models import Item, PhotoDetection
from domovnik.errors import Conflict, ValidationFailed
from domovnik.schemas import ItemCreate, PlacementIn
from domovnik.services import files, items, locations


@pytest.fixture(autouse=True)
def _files_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("FILES_DIR", str(tmp_path / "files"))
    get_settings.cache_clear()
    yield
    override_provider(None)
    get_settings.cache_clear()


def jpeg(color: tuple[int, int, int] = (200, 120, 40), size: tuple[int, int] = (640, 480)) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def payload(*detections: dict[str, Any], scene: str = "Police") -> str:
    return json.dumps({"scene": scene, "detections": list(detections)}, ensure_ascii=False)


def det(name: str, **kw: Any) -> dict[str, Any]:
    return {
        "label": name.lower(),
        "name": name,
        "confidence": 0.9,
        "quantity": 1,
        "category_path": ["Nářadí"],
        "tags": [],
        **kw,
    }


def make_analysis(db: Session, ctx: ActorContext, provider: FakeProvider, **kw: Any):
    rec, _ = files.store(db, ctx, jpeg(), "foto.jpg")
    analysis = vision.create_analysis(db, ctx, file_id=rec.id, **kw)
    vision.run_analysis(db, analysis.id, provider)
    return analysis


def test_analysis_creates_detections_with_duplicates_and_location_suggestions(
    db: Session, ctx: ActorContext
) -> None:
    garaz = locations.get_or_create_path(db, ctx, ["Dům", "Garáž"])
    sklep = locations.get_or_create_path(db, ctx, ["Dům", "Sklep"])
    existing = items.create_item(
        db, ctx, ItemCreate(name="Akušroubovák", placements=[PlacementIn(location_id=garaz.id)])
    )
    items.create_item(
        db, ctx, ItemCreate(name="Lepicí páska", placements=[PlacementIn(location_id=sklep.id)])
    )

    model_output = (
        "```json\n"
        + payload(
            det("Akušroubovák", bbox=[0.1, 0.1, 0.3, 0.3], brand="Bosch"),
            det("Lepicí páska malířská", bbox=[1.2, -0.1, 0.5, 0.5], quantity=3),
            {"label": "", "name": ""},  # nepoužitelná položka se přeskočí
            det("Nová věc bez kontextu", confidence=7),
        )
        + "\n```"
    )
    provider = FakeProvider([text(model_output)])
    analysis = make_analysis(db, ctx, provider, hint="věci po babičce")

    out = vision.analysis_out(db, analysis)
    assert out["status"] == "done" and out["scene"] == "Police"
    by_name = {d["suggested"]["name"]: d for d in out["detections"]}
    assert set(by_name) == {"Akušroubovák", "Lepicí páska malířská", "Nová věc bez kontextu"}

    a = by_name["Akušroubovák"]
    assert a["matched_item"]["id"] == str(existing.id)  # duplicita
    assert a["suggested_location"]["full_name"] == "Dům › Garáž"
    assert "Podobná" in a["suggested_location"]["reason"]
    tape = by_name["Lepicí páska malířská"]
    assert tape["bbox"] is None or all(0.0 <= v <= 1.0 for v in tape["bbox"])  # oříznuto do 0–1
    assert by_name["Nová věc bez kontextu"]["confidence"] == 1.0  # clamp
    assert by_name["Nová věc bez kontextu"]["matched_item"] is None
    call = provider.calls[0]
    assert "věci po babičce" in call["messages"][0].content and "DATA" in call["system"]
    assert call["messages"][0].images and call["json_schema"] is vision.SCHEMA


def test_context_location_is_suggested_when_nothing_similar(db: Session, ctx: ActorContext) -> None:
    police = locations.get_or_create_path(db, ctx, ["Dům", "Dílna", "Police 2"])
    analysis = make_analysis(
        db, ctx, FakeProvider([text(payload(det("Úplně nová věc")))]), context_location_id=police.id
    )
    d = vision.analysis_out(db, analysis)["detections"][0]
    assert d["suggested_location"]["id"] == str(police.id)
    assert "pořízena" in d["suggested_location"]["reason"]


def test_failures_are_stored_not_raised(db: Session, ctx: ActorContext) -> None:
    class Broken(FakeProvider):
        def chat(self, *a, **k):
            raise ProviderError("limit")

    assert make_analysis(db, ctx, Broken()).error == "limit"
    bad = make_analysis(db, ctx, FakeProvider([text("tohle není json")]))
    assert bad.status == "failed" and "JSON" in (bad.error or "")
    rec, _ = files.store(db, ctx, b"%PDF-1.4\n%%EOF\n", "x.pdf")
    with pytest.raises(ValidationFailed):
        vision.create_analysis(db, ctx, file_id=rec.id)  # PDF není fotka


def test_commit_creates_items_merges_rejects_attaches_crops_and_undo(
    db: Session, ctx: ActorContext
) -> None:
    garaz = locations.get_or_create_path(db, ctx, ["Dům", "Garáž"])
    existing = items.create_item(
        db,
        ctx,
        ItemCreate(
            name="Metr svinovací",
            placements=[PlacementIn(location_id=garaz.id, quantity=Decimal(1))],
        ),
    )
    analysis = make_analysis(
        db,
        ctx,
        FakeProvider(
            [
                text(
                    payload(
                        det(
                            "Akušroubovák",
                            bbox=[0.1, 0.1, 0.4, 0.4],
                            brand="Bosch",
                            category_path=["Nářadí", "Elektrické"],
                        ),
                        det("Metr svinovací", bbox=[0.5, 0.5, 0.3, 0.3], quantity=2),
                        det("Kabel", bbox=[0.0, 0.7, 0.2, 0.2]),
                    )
                )
            ]
        ),
        context_location_id=garaz.id,
    )
    dets = {d["suggested"]["name"]: d for d in vision.analysis_out(db, analysis)["detections"]}

    decisions = [
        vision.Decision(
            detection_id=uuid.UUID(dets["Akušroubovák"]["id"]),
            action="accept",
            overrides=vision.Overrides(
                name="Aku šroubovák Bosch", tags=["nářadí"], quantity=Decimal(1)
            ),
        ),
        vision.Decision(detection_id=uuid.UUID(dets["Metr svinovací"]["id"]), action="merge"),
        vision.Decision(detection_id=uuid.UUID(dets["Kabel"]["id"]), action="reject"),
    ]
    result = vision.commit_analysis(db, ctx, analysis.id, decisions)
    assert len(result.created_item_ids) == 1 and result.merged_item_ids == [existing.id]

    new = items.get_item_out(db, result.created_item_ids[0])
    assert new.name == "Aku šroubovák Bosch" and new.brand == "Bosch" and new.tags == ["nářadí"]
    assert new.category_path == "Nářadí › Elektrické"
    assert new.placements[0].location_path == "Dům › Garáž"  # z kontextu fotky
    assert new.primary_file_id is not None and new.file_count == 1  # ořez podle rámečku
    assert items.get_item_out(db, existing.id).total_quantity == 3  # 1 + 2 sloučeno

    statuses = {d.suggested["name"]: d.status for d in db.execute(select(PhotoDetection)).scalars()}
    assert statuses == {"Akušroubovák": "edited", "Metr svinovací": "merged", "Kabel": "rejected"}

    cs = changesets.list_change_sets(db)[0]
    assert cs.status == "applied"
    changesets.undo_change_set(db, ctx, cs.id)
    trashed = db.get(Item, new.id)
    assert trashed is not None and trashed.deleted_at is not None
    assert items.get_item_out(db, existing.id).total_quantity == 1

    with pytest.raises(Conflict):  # stejné detekce podruhé nejdou
        vision.commit_analysis(db, ctx, analysis.id, decisions[:1])


def test_commit_validation(db: Session, ctx: ActorContext) -> None:
    analysis = make_analysis(db, ctx, FakeProvider([text(payload(det("Něco")))]))
    d = vision.analysis_out(db, analysis)["detections"][0]
    with pytest.raises(ValidationFailed):  # merge bez podobné věci
        vision.commit_analysis(
            db, ctx, analysis.id, [vision.Decision(detection_id=uuid.UUID(d["id"]), action="merge")]
        )
    with pytest.raises(ValidationFailed):  # cizí detekce
        vision.commit_analysis(
            db, ctx, analysis.id, [vision.Decision(detection_id=uuid.uuid4(), action="accept")]
        )
    failed = make_analysis(db, ctx, FakeProvider([text("není json")]))
    with pytest.raises(Conflict):
        vision.commit_analysis(db, ctx, failed.id, [])


def test_storage_plan(db: Session, ctx: ActorContext) -> None:
    analysis = make_analysis(
        db, ctx, FakeProvider([text(payload(det("Kladivo"), det("Šroubovák")))])
    )
    ids = [d["id"] for d in vision.analysis_out(db, analysis)["detections"]]
    plan_json = json.dumps(
        {
            "summary": "Ulož to dohromady.",
            "steps": [
                {
                    "title": "Krok 1",
                    "detection_ids": [ids[0], str(uuid.uuid4())],
                    "location_path": ["Dům", "Garáž"],
                },
                {"detail": "bez titulku se zahodí"},
            ],
        }
    )
    plan = vision.storage_plan(db, analysis.id, FakeProvider([text(plan_json)]))
    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["detection_ids"] == [ids[0]]  # cizí id odfiltrováno


# --- HTTP ------------------------------------------------------------------------------------


def test_photo_analysis_over_http(clean_db: None) -> None:
    from fastapi.testclient import TestClient

    from domovnik.main import app

    override_provider(
        FakeProvider(
            [text(json.dumps(DEMO_DETECTIONS)), text(json.dumps({"steps": [{"title": "Ulož"}]}))]
        )
    )
    with TestClient(app) as c:
        me = c.post(
            "/api/v1/auth/setup", json={"username": "admin", "password": "correct horse battery"}
        ).json()
        h = {"X-CSRF-Token": me["csrf_token"]}
        loc = c.post("/api/v1/locations", json={"name": "Garáž"}, headers=h).json()
        up = c.post("/api/v1/files", files={"file": ("f.jpg", jpeg(), "image/jpeg")}, headers=h)
        assert up.status_code == 201, up.text
        body_up = up.json()
        file_id = body_up["file"]["id"] if "file" in body_up else body_up["id"]

        r = c.post(
            "/api/v1/photos/analyze",
            json={"file_id": file_id, "context_location_id": loc["id"]},
            headers=h,
        )
        assert r.status_code == 202
        aid = r.json()["id"]
        out: dict[str, Any] = {}
        for _ in range(100):  # analýza běží na pozadí
            out = c.get(f"/api/v1/photos/analyses/{aid}").json()
            if out["status"] in ("done", "failed"):
                break
            time.sleep(0.1)
        assert out["status"] == "done", out
        assert len(out["detections"]) == 3
        assert out["detections"][0]["confidence"] >= out["detections"][-1]["confidence"]

        plan = c.post(f"/api/v1/photos/analyses/{aid}/plan", headers=h)
        assert plan.status_code == 200 and plan.json()["steps"][0]["title"] == "Ulož"

        decisions = [
            {"detection_id": d["id"], "action": "accept" if d["confidence"] >= 0.8 else "reject"}
            for d in out["detections"]
        ]
        res = c.post(
            f"/api/v1/photos/analyses/{aid}/commit", json={"decisions": decisions}, headers=h
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert len(body["created_item_ids"]) == 2 and body["change_set"]["status"] == "applied"
        listing = c.get("/api/v1/items").json()
        assert listing["total"] == 2
        assert all(i["placements"][0]["location_path"] == "Garáž" for i in listing["items"])
        assert all(i["file_count"] == 1 for i in listing["items"])

        cs_id = body["change_set"]["id"]
        assert (
            c.post(f"/api/v1/ai/change-sets/{cs_id}/undo", headers=h).json()["status"] == "undone"
        )
        assert c.get("/api/v1/items").json()["total"] == 0

    with TestClient(app) as admin:
        admin.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "correct horse battery"}
        )
        csrf = admin.get("/api/v1/auth/me").json()["csrf_token"]
        admin.post(
            "/api/v1/users",
            json={"username": "v", "password": "correct horse battery", "role": "viewer"},
            headers={"X-CSRF-Token": csrf},
        )
    with TestClient(app) as v:
        vm = v.post(
            "/api/v1/auth/login", json={"username": "v", "password": "correct horse battery"}
        ).json()
        r = v.post(
            f"/api/v1/photos/analyses/{aid}/commit",
            headers={"X-CSRF-Token": vm["csrf_token"]},
            json={"decisions": [{"detection_id": str(uuid.uuid4()), "action": "reject"}]},
        )
        assert r.status_code in (403, 404)
