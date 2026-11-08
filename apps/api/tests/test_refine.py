"""Úpravy konceptu kontroly nálezů z fotky asistentem: návrhy úprav, očištění, žádný zápis dat."""

from __future__ import annotations

import io
import json
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PIL import Image as PILImage
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domovnik.ai import refine, vision
from domovnik.ai.providers import override_provider
from domovnik.ai.providers.base import ProviderError
from domovnik.ai.providers.fake import FakeProvider, text
from domovnik.config import get_settings
from domovnik.context import ActorContext
from domovnik.db.models import AiChangeSet, Item
from domovnik.errors import Conflict, NotFound
from domovnik.schemas import ItemCreate, KnowledgeCreate, PlacementIn
from domovnik.services import files, items, knowledge, locations


@pytest.fixture(autouse=True)
def _files_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("FILES_DIR", str(tmp_path / "files"))
    get_settings.cache_clear()
    yield
    override_provider(None)
    get_settings.cache_clear()


def jpeg() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (320, 240), (200, 120, 40)).save(buf, "JPEG")
    return buf.getvalue()


def det(name: str, confidence: float, **kw: Any) -> dict[str, Any]:
    return {
        "label": name.lower(),
        "name": name,
        "confidence": confidence,
        "quantity": 1,
        "category_path": ["Nářadí"],
        "tags": [],
        **kw,
    }


def make_analysis(db: Session, ctx: ActorContext, *dets: dict[str, Any], **kw: Any):  # type: ignore[no-untyped-def]
    rec, _ = files.store(db, ctx, jpeg(), "foto.jpg")
    analysis = vision.create_analysis(db, ctx, file_id=rec.id, **kw)
    out = json.dumps({"scene": "Police", "detections": list(dets)}, ensure_ascii=False)
    vision.run_analysis(db, analysis.id, FakeProvider([text(out)]))
    return analysis


def reply(**data: Any) -> FakeProvider:
    return FakeProvider([text(json.dumps(data, ensure_ascii=False))])


def setup(db: Session, ctx: ActorContext):  # type: ignore[no-untyped-def]
    garaz = locations.get_or_create_path(db, ctx, ["Dům", "Garáž"])
    locations.get_or_create_path(db, ctx, ["Dům", "Garáž", "Police 2"])
    items.create_item(
        db, ctx, ItemCreate(name="Akušroubovák", placements=[PlacementIn(location_id=garaz.id)])
    )
    # pořadí detekcí: podle jistoty sestupně → 1 Akušroubovák (duplicita), 2 Šrouby, 3 Pásek
    return make_analysis(
        db,
        ctx,
        det("Akušroubovák", 0.95),
        det("Šrouby", 0.9),
        det("Pásek", 0.7),
        context_location_id=garaz.id,
    )


def test_edits_are_sanitized_resolved_and_nothing_is_saved(db: Session, ctx: ActorContext) -> None:
    analysis = setup(db, ctx)
    before_items = db.execute(select(func.count()).select_from(Item)).scalar_one()
    before_sets = db.execute(select(func.count()).select_from(AiChangeSet)).scalar_one()

    provider = reply(
        reply="Upravil jsem šrouby a sloučil duplicitu.",
        edits=[
            {"index": 1, "choice": "merge"},
            {
                "index": 2,
                "name": "  Šrouby 4x40 ",
                "quantity": 50,
                "category_path": ["Drobnosti", "Spojovací"],
                "location_path": ["dům", "garáž", "police 2"],  # existující (bez ohledu na písmena)
                "choice": "accept",
            },
            {"index": 3, "choice": "merge"},  # není duplicita → volba se zahodí a úprava zmizí
            {"index": 3, "location_path": ["Dům", "Nová krabice"], "tags": ["krabice"]},
            {"index": 9, "choice": "accept"},  # neexistující položka
            {"index": 2, "quantity": -4},  # neplatné množství → prázdná úprava
            {"index": "x", "choice": "accept"},  # nesmysl
            "není objekt",
        ],
    )
    out = refine.refine(
        db, analysis.id, refine.RefineIn(text="uprav to", draft=[], history=[]), provider
    )
    assert out["reply"].startswith("Upravil jsem")
    assert [e["index"] for e in out["edits"]] == [1, 2, 3]

    merge, upd, newloc = out["edits"]
    assert merge["choice"] == "merge" and merge["changes"] == {}
    assert upd["choice"] == "accept"
    assert upd["changes"]["name"] == "Šrouby 4x40" and upd["changes"]["quantity"] == 50.0
    assert upd["changes"]["category_path"] == ["Drobnosti", "Spojovací"]
    police = locations.find_path(db, ["Dům", "Garáž", "Police 2"])
    assert police is not None
    assert upd["changes"]["location_id"] == str(police.id)  # existující → id
    assert (
        upd["location"]["is_new"] is False and upd["location"]["label"] == "dům › garáž › police 2"
    )
    assert newloc["changes"]["location_path"] == ["Dům", "Nová krabice"]  # nové → cesta
    assert newloc["location"]["is_new"] is True and "location_id" not in newloc["changes"]
    assert newloc["changes"]["tags"] == ["krabice"]
    assert "choice" not in newloc  # merge u položky bez duplicity zahozen

    # koncept nic nezapsal: žádné nové věci, žádný balíček změn, nové umístění nevzniklo
    assert db.execute(select(func.count()).select_from(Item)).scalar_one() == before_items
    assert db.execute(select(func.count()).select_from(AiChangeSet)).scalar_one() == before_sets
    assert locations.find_path(db, ["Dům", "Nová krabice"]) is None


def test_prompt_contains_numbered_state_draft_overrides_knowledge_and_history(
    db: Session, ctx: ActorContext
) -> None:
    analysis = setup(db, ctx)
    knowledge.create_entry(
        db,
        ctx,
        KnowledgeCreate(title="Šrouby", content="Drobné šrouby patří do krabic v dílně."),
    )
    dets = vision.analysis_out(db, analysis)["detections"]
    provider = reply(reply="Nic.", edits=[])
    refine.refine(
        db,
        analysis.id,
        refine.RefineIn(
            text="co je v seznamu?",
            draft=[
                refine.DraftItem(
                    detection_id=uuid.UUID(dets[1]["id"]),
                    choice="accept",
                    overrides=vision.Overrides(name="Moje šrouby", quantity=25),
                )
            ],
            history=[
                refine.Turn(role="user", text="ahoj"),
                refine.Turn(role="assistant", text="Ahoj, co upravit?"),
            ],
        ),
        provider,
    )
    call = provider.calls[0]
    assert call["json_schema"] is refine.REFINE_SCHEMA
    system = call["system"]
    assert "NIC se neukládá" in system or "nic se neukládá" in system
    assert "Drobné šrouby patří do krabic v dílně." in system
    assert "Dům › Garáž › Police 2" in system and "Fotka je z umístění: Dům › Garáž" in system
    msgs = call["messages"]
    assert [m.role for m in msgs] == ["user", "assistant", "user"]
    last = msgs[-1].content
    assert "Pokyn uživatele: co je v seznamu?" in last
    state = json.loads(last.split("Aktuální koncept (data):\n", 1)[1])
    assert [s["index"] for s in state] == [1, 2, 3]
    assert state[0]["duplicate_of"].startswith("Akušroubovák")
    assert state[1]["name"] == "Moje šrouby" and state[1]["quantity"] == 25.0
    assert state[1]["choice"] == "accept" and state[2]["choice"] == "pending"


def test_errors_and_empty_reply(db: Session, ctx: ActorContext) -> None:
    analysis = setup(db, ctx)
    body = refine.RefineIn(text="x")
    with pytest.raises(ProviderError):
        refine.refine(db, analysis.id, body, FakeProvider([text("tohle není json")]))
    with pytest.raises(ProviderError):
        refine.refine(db, analysis.id, body, FakeProvider([text("[1, 2]")]))
    none = refine.refine(db, analysis.id, body, reply(reply="", edits=[]))
    assert none == {"reply": "Nic jsem neměnil.", "edits": []}
    assert (
        refine.refine(
            db, analysis.id, body, reply(reply="", edits=[{"index": 1, "choice": "reject"}])
        )["reply"]
        == "Hotovo."
    )
    with pytest.raises(NotFound):
        refine.refine(db, uuid.uuid4(), body, reply(reply="x", edits=[]))
    failed = make_analysis(db, ctx, det("X", 0.5))
    failed.status = "queued"
    db.flush()
    with pytest.raises(Conflict):
        refine.refine(db, failed.id, body, reply(reply="x", edits=[]))


def test_refine_over_http_then_commit_with_overrides(clean_db: None) -> None:
    from fastapi.testclient import TestClient

    from domovnik.main import app

    out_json = json.dumps(
        {"scene": "Police", "detections": [det("Šrouby", 0.9), det("Pásek", 0.8)]},
        ensure_ascii=False,
    )
    override_provider(
        FakeProvider(
            [
                text(out_json),
                text(
                    json.dumps(
                        {
                            "reply": "Přejmenoval jsem šrouby a přijal vše.",
                            "edits": [
                                {"index": 1, "name": "Šrouby 4x40", "choice": "accept"},
                                {
                                    "index": 2,
                                    "choice": "accept",
                                    "location_path": ["Garáž", "Police 9"],
                                },
                            ],
                        },
                        ensure_ascii=False,
                    )
                ),
            ]
        )
    )
    with TestClient(app) as c:
        me = c.post(
            "/api/v1/auth/setup", json={"username": "admin", "password": "correct horse battery"}
        ).json()
        h = {"X-CSRF-Token": me["csrf_token"]}
        c.post("/api/v1/locations", json={"name": "Garáž"}, headers=h)
        up = c.post("/api/v1/files", files={"file": ("f.jpg", jpeg(), "image/jpeg")}, headers=h)
        body_up = up.json()
        file_id = body_up["file"]["id"] if "file" in body_up else body_up["id"]
        aid = c.post("/api/v1/photos/analyze", json={"file_id": file_id}, headers=h).json()["id"]
        a: dict[str, Any] = {}
        for _ in range(100):
            a = c.get(f"/api/v1/photos/analyses/{aid}").json()
            if a["status"] in ("done", "failed"):
                break
            time.sleep(0.1)
        assert a["status"] == "done"

        r = c.post(
            f"/api/v1/photos/analyses/{aid}/refine",
            json={"text": "přejmenuj šrouby a přijmi vše", "draft": [], "history": []},
            headers=h,
        )
        assert r.status_code == 200, r.text
        res = r.json()
        assert res["reply"].startswith("Přejmenoval")
        assert c.get("/api/v1/items").json()["total"] == 0  # koncept nic neuložil
        assert [x["name"] for x in c.get("/api/v1/locations").json()] == ["Garáž"]

        # klient úpravy použije a pošle je jako přepsání při schválení
        e1, e2 = res["edits"]
        decisions = [
            {
                "detection_id": e["detection_id"],
                "action": e["choice"],
                "overrides": e["changes"],
            }
            for e in (e1, e2)
        ]
        done = c.post(
            f"/api/v1/photos/analyses/{aid}/commit", json={"decisions": decisions}, headers=h
        )
        assert done.status_code == 200, done.text
        listing = c.get("/api/v1/items").json()["items"]
        assert sorted(i["name"] for i in listing) == ["Pásek", "Šrouby 4x40"]
        paths = {
            i["name"]: (i["placements"][0]["location_path"] if i["placements"] else None)
            for i in listing
        }
        assert paths["Pásek"] == "Garáž › Police 9"  # nové umístění vzniklo až při schválení
        assert paths["Šrouby 4x40"] is None  # bez místa v úpravě i na fotce

        # bez přihlášení / s neznámou analýzou
        assert (
            c.post(
                f"/api/v1/photos/analyses/{uuid.uuid4()}/refine", json={"text": "x"}, headers=h
            ).status_code
            == 404
        )
    with TestClient(app) as anon:
        assert anon.post(
            f"/api/v1/photos/analyses/{aid}/refine", json={"text": "x"}
        ).status_code in (401, 403)
