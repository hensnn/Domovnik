"""Testy knihovny znalostí pro AI: správa, vkládání do promptů, návrh od AI a bezpečnost."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from domovnik.ai import agent, changesets, vision
from domovnik.ai import ops as ops_mod
from domovnik.ai.providers import override_provider
from domovnik.ai.providers.fake import FakeProvider, call, text
from domovnik.ai.tools import ToolRuntime, tool_specs
from domovnik.api.auth import login_limiter
from domovnik.context import ActorContext, bind_context
from domovnik.db.models import AiKnowledge, PhotoAnalysis, User
from domovnik.errors import Conflict, ValidationFailed
from domovnik.main import app
from domovnik.schemas import KnowledgeCreate, KnowledgeUpdate
from domovnik.services import knowledge
from domovnik.services import settings as settings_service

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def _reset_provider() -> Iterator[None]:
    yield
    override_provider(None)


def add(db: Session, ctx: ActorContext, title: str, content: str, **kw: Any) -> AiKnowledge:
    return knowledge.create_entry(db, ctx, KnowledgeCreate(title=title, content=content, **kw))


def member(db: Session) -> tuple[User, ActorContext]:
    u = User(username="clen", display_name="Člen", password_hash=None, role="member")
    db.add(u)
    db.flush()
    c = ActorContext(actor_id=u.id, source="ai")
    bind_context(db, c)
    return u, c


# --- služba ---------------------------------------------------------------------------------


def test_crud_validation_and_optimistic_locking(db: Session, ctx: ActorContext) -> None:
    e = add(db, ctx, "  Nářadí  ", "Nářadí patří do garáže.", topic="rules")
    assert e.title == "Nářadí" and e.enabled and e.source == "admin" and e.version == 1

    upd = knowledge.update_entry(
        db, ctx, e.id, KnowledgeUpdate(content="Nářadí patří do dílny.", version=1)
    )
    assert upd.content == "Nářadí patří do dílny." and upd.version == 2
    with pytest.raises(Conflict):  # zastaralá verze
        knowledge.update_entry(db, ctx, e.id, KnowledgeUpdate(title="Jiné", version=1))
    with pytest.raises(ValidationFailed):
        knowledge.update_entry(db, ctx, e.id, KnowledgeUpdate(title="   "))

    knowledge.delete_entry(db, ctx, e.id)
    assert knowledge.list_entries(db) == []


def test_order_topics_and_only_enabled(db: Session, ctx: ActorContext) -> None:
    add(db, ctx, "B", "druhé", sort_order=2)
    add(db, ctx, "A", "první", sort_order=1, topic="household")
    add(db, ctx, "Vypnuté", "x", enabled=False)
    assert [e.title for e in knowledge.list_entries(db)] == ["Vypnuté", "A", "B"]
    assert [e.title for e in knowledge.list_entries(db, enabled_only=True)] == ["A", "B"]
    assert [e.title for e in knowledge.list_entries(db, topic="household")] == ["A"]


def test_prompt_block_limit_disabled_and_setting_off(db: Session, ctx: ActorContext) -> None:
    add(db, ctx, "Šrouby", "Drobné šrouby patří do krabic v dílně.", topic="rules")
    add(db, ctx, "Dlouhé", "x" * 1500)
    add(db, ctx, "Vypnuté", "tajné", enabled=False)

    full = knowledge.prompt_block(db)
    assert "[Pravidla uspořádání] Šrouby: Drobné šrouby patří do krabic v dílně." in full.text
    assert "tajné" not in full.text and full.omitted == 0

    small = knowledge.prompt_block(db, max_chars=120)
    assert small.included == 1 and small.omitted == 1 and "Dlouhé" not in small.text
    hint = knowledge.prompt_section(db, tool_hint=True)
    assert hint.startswith("Znalosti o domácnosti od správce")

    settings_service.set_value(db, ctx, "ai.knowledge_max_chars", 500, actor_is_admin=True)
    assert "search_knowledge" in knowledge.prompt_section(db)

    settings_service.set_value(db, ctx, "ai.knowledge_enabled", False, actor_is_admin=True)
    assert knowledge.prompt_section(db) == ""


def test_search_ignores_diacritics_and_disabled(db: Session, ctx: ActorContext) -> None:
    add(db, ctx, "Zimní pneumatiky", "Sklep, police vlevo.")
    add(db, ctx, "Skryté", "pneumatiky v garáži", enabled=False)
    assert [e.title for e in knowledge.search_entries(db, "zimni pneu")] == ["Zimní pneumatiky"]
    assert knowledge.search_entries(db, "neexistuje") == []
    assert len(knowledge.search_entries(db, "")) == 1  # prázdný dotaz = začátek knihovny


# --- AI: prompty a nástroj --------------------------------------------------------------------


def test_agent_prompt_contains_knowledge_and_asks_not_to_repeat(
    db: Session, ctx: ActorContext, user: User
) -> None:
    add(db, ctx, "Baterie", "Baterie vždy do šuplíku v kuchyni.", topic="rules")
    add(db, ctx, "Skryté", "tohle AI nesmí vidět", enabled=False)
    prompt = agent.build_system_prompt(db, user_id=user.id, voice=False, context_location=None)
    assert "Baterie vždy do šuplíku v kuchyni." in prompt
    assert "NEPTEJ znovu" in prompt and "tohle AI nesmí vidět" not in prompt
    assert "search_knowledge" in prompt  # pravidlo 10 + nástroj

    settings_service.set_value(db, ctx, "ai.knowledge_enabled", False, actor_is_admin=True)
    off = agent.build_system_prompt(db, user_id=user.id, voice=False, context_location=None)
    assert "Baterie vždy do šuplíku" not in off


def test_vision_prompt_gets_the_library(db: Session, ctx: ActorContext, user: User) -> None:
    add(db, ctx, "Dílna", "Elektrické nářadí patří do kufrů v dílně.", topic="rules")
    analysis = PhotoAnalysis(context_location_id=None, user_hint=None)
    prompt = vision.build_prompt(db, analysis)
    assert "Elektrické nářadí patří do kufrů v dílně." in prompt


def test_search_knowledge_tool_available_without_write(
    db: Session, ctx: ActorContext, user: User
) -> None:
    add(db, ctx, "Pneumatiky", "Zimní pneumatiky jsou ve sklepě.")
    assert "search_knowledge" in {s.name for s in tool_specs(can_write=False, voice_confirm=False)}
    rt = ToolRuntime(db=db, ctx=ctx, user_id=user.id, can_write=False)
    out = rt.call("search_knowledge", {"query": "pneumatiky"})
    assert out["entries"][0]["content"] == "Zimní pneumatiky jsou ve sklepě."

    settings_service.set_value(db, ctx, "ai.knowledge_enabled", False, actor_is_admin=True)
    assert rt.call("search_knowledge", {"query": "pneumatiky"})["entries"] == []


# --- AI navrhuje znalost: vždy s potvrzením, admin vs. člen, undo -------------------------------


def _op(title: str = "Šrouby", content: str = "Drobné šrouby do krabic v dílně.") -> dict[str, Any]:
    return {"op": "add_knowledge", "title": title, "content": content, "topic": "rules"}


def test_add_knowledge_needs_confirmation_even_with_full_trust(
    db: Session, ctx: ActorContext, user: User
) -> None:
    settings_service.set_value(db, ctx, "ai.trust_level", "auto_all", actor_is_admin=True)
    cs = changesets.propose(db, ctx, summary="Pravidlo", operations=[_op()])
    rows = changesets.operations(db, cs.id)
    assert changesets.has_never_auto(rows) and changesets.is_risky(rows)
    assert not changesets.can_auto_apply(db, rows, user_id=user.id)
    assert changesets.describe_change_set(db, cs)["needs_ui_confirmation"] is True
    assert knowledge.list_entries(db) == []  # nic se nezapsalo

    # hlasem se nepotvrdí
    rt = ToolRuntime(db=db, ctx=ctx, user_id=user.id, can_write=True, voice=True)
    assert "jen v aplikaci" in rt.call("confirm_pending_changes", {"approve": True})["error"]


def test_admin_confirmation_enables_entry_and_undo_removes_it(
    db: Session, ctx: ActorContext
) -> None:
    cs = changesets.propose(db, ctx, summary="Pravidlo", operations=[_op()])
    done = changesets.apply_change_set(db, ctx, cs.id)
    assert done.status == "applied"
    (entry,) = knowledge.list_entries(db)
    assert entry.source == "ai" and entry.enabled and entry.topic == "rules"
    assert "Drobné šrouby" in knowledge.prompt_block(db).text

    changesets.undo_change_set(db, ctx, cs.id)
    assert knowledge.list_entries(db) == []


def test_member_confirmation_creates_disabled_entry_waiting_for_admin(db: Session) -> None:
    _, mctx = member(db)
    cs = changesets.propose(db, mctx, summary="Pravidlo", operations=[_op()])
    changesets.apply_change_set(db, mctx, cs.id)
    (entry,) = knowledge.list_entries(db)
    assert entry.source == "ai" and not entry.enabled
    assert knowledge.prompt_block(db).text == ""  # do promptu se nedostane


def test_ai_cannot_use_internal_delete_knowledge_op(db: Session, ctx: ActorContext) -> None:
    e = add(db, ctx, "Pravidlo", "text")
    with pytest.raises(ValidationFailed):
        changesets.propose(
            db,
            ctx,
            summary="x",
            operations=[{"op": "delete_knowledge", "knowledge_id": str(e.id)}],
        )
    with pytest.raises(ValidationFailed):  # příliš dlouhý text
        changesets.propose(db, ctx, summary="x", operations=[_op(content="x" * 2001)])
    assert db.execute(select(AiKnowledge)).scalars().all()  # záznam zůstal
    _ = ops_mod


def test_full_turn_ai_learns_a_rule_and_user_confirms(
    db: Session, ctx: ActorContext, user: User
) -> None:
    script = [
        call("propose_changes", summary="Zapamatovat pravidlo", operations=[_op()]),
        text("Navrhuji uložit pravidlo. Potvrď ho v aplikaci."),
    ]
    res = agent.run_turn(
        db,
        ctx,
        user_id=user.id,
        can_write=True,
        text="Drobné šrouby dávej vždy do krabic v dílně.",
        provider=FakeProvider(script),
    )
    cs = res.change_sets[0]
    assert cs["status"] == "proposed" and cs["needs_ui_confirmation"]
    assert knowledge.list_entries(db) == []


# --- HTTP: čtení pro všechny, správa jen admin --------------------------------------------------


@pytest.fixture
def client(clean_db: None) -> Iterator[TestClient]:
    login_limiter._events.clear()
    with TestClient(app) as c:
        r = c.post("/api/v1/auth/setup", json={"username": "admin", "password": PASSWORD})
        assert r.status_code == 201, r.text
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        yield c


def ok(r: Any, code: int = 200) -> Any:
    assert r.status_code == code, f"{r.status_code}: {r.text}"
    return r.json() if r.content else None


def test_knowledge_http_admin_manages_others_only_read_enabled(client: TestClient) -> None:
    a = ok(
        client.post(
            "/api/v1/knowledge",
            json={"title": "Šrouby", "content": "Do krabic v dílně.", "topic": "rules"},
        ),
        201,
    )
    b = ok(
        client.post(
            "/api/v1/knowledge",
            json={"title": "Koncept", "content": "Čeká na schválení.", "enabled": False},
        ),
        201,
    )
    assert a["version"] == 1 and a["source"] == "admin"
    assert client.post("/api/v1/knowledge", json={"title": "", "content": "x"}).status_code == 422
    assert (
        client.post(
            "/api/v1/knowledge", json={"title": "T", "content": "x", "topic": "nic"}
        ).status_code
        == 422
    )

    # optimistické zamykání přes If-Match
    p = ok(
        client.patch(
            f"/api/v1/knowledge/{a['id']}",
            json={"content": "Do krabic v dílně a ve sklepě."},
            headers={"If-Match": "1"},
        )
    )
    assert p["version"] == 2
    stale = client.patch(
        f"/api/v1/knowledge/{a['id']}", json={"title": "Nové"}, headers={"If-Match": "1"}
    )
    assert stale.status_code == 409

    assert {e["title"] for e in ok(client.get("/api/v1/knowledge"))} == {"Šrouby", "Koncept"}
    assert [e["title"] for e in ok(client.get("/api/v1/knowledge?topic=rules"))] == ["Šrouby"]

    ok(
        client.post(
            "/api/v1/users", json={"username": "clen", "password": PASSWORD, "role": "member"}
        ),
        201,
    )
    with TestClient(app) as m:
        me = ok(m.post("/api/v1/auth/login", json={"username": "clen", "password": PASSWORD}))
        mh = {"X-CSRF-Token": me["csrf_token"]}
        titles = {e["title"] for e in ok(m.get("/api/v1/knowledge"))}
        assert titles == {"Šrouby"}  # vypnuté nevidí
        assert (
            m.post("/api/v1/knowledge", json={"title": "X", "content": "y"}, headers=mh).status_code
            == 403
        )
        assert (
            m.patch(f"/api/v1/knowledge/{a['id']}", json={"title": "X"}, headers=mh).status_code
            == 403
        )
        assert m.delete(f"/api/v1/knowledge/{a['id']}", headers=mh).status_code == 403

    ok(client.delete(f"/api/v1/knowledge/{b['id']}"), 204)
    assert client.delete(f"/api/v1/knowledge/{b['id']}").status_code == 404
    assert [e["title"] for e in ok(client.get("/api/v1/knowledge"))] == ["Šrouby"]
