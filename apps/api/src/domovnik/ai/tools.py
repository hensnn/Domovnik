"""Nástroje asistenta nad servisní vrstvou. Čtecí jsou volné, zapisovací jen přes návrh změn."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from domovnik.ai import changesets
from domovnik.ai import ops as ops_mod
from domovnik.ai.providers.base import ToolSpec
from domovnik.context import ActorContext
from domovnik.db.models import AiChangeSet, ItemPlacement
from domovnik.errors import DomainError, ValidationFailed
from domovnik.schemas import ItemOut
from domovnik.services import categories, items, locations, search, stats
from domovnik.services import settings as settings_service
from domovnik.services.search import ItemFilter

MAX_RESULTS = 25


# --- Kompaktní podoba dat pro model (šetří tokeny) -----------------------------------------


def compact_item(i: ItemOut) -> dict[str, Any]:
    return {
        "id": str(i.id),
        "label": i.label_code,
        "name": i.name,
        "category": i.category_path,
        "status": i.status,
        "total_quantity": str(i.total_quantity),
        "unit": i.unit,
        "locations": [
            {
                "location_id": str(p.location_id),
                "path": p.location_path,
                "quantity": str(p.quantity),
            }
            for p in i.placements
        ],
        "tags": i.tags,
        **({"brand": i.brand} if i.brand else {}),
        **({"notes": i.notes} if i.notes else {}),
        **({"aliases": i.aliases} if i.aliases else {}),
    }


def _schema_from_models() -> dict[str, Any]:
    """Plochý JSON schema pro položku operace (sjednocení polí všech povolených operací)."""
    props: dict[str, Any] = {}
    for model in (
        ops_mod.CreateItemOp,
        ops_mod.UpdateItemOp,
        ops_mod.MoveItemOp,
        ops_mod.SetQuantityOp,
        ops_mod.DeleteItemOp,
        ops_mod.CreateLocationOp,
        ops_mod.UpdateLocationOp,
        ops_mod.MoveLocationOp,
        ops_mod.ArchiveLocationOp,
        ops_mod.CreateCategoryOp,
        ops_mod.UpdateCategoryOp,
        ops_mod.MergeCategoriesOp,
        ops_mod.DeleteCategoryOp,
        ops_mod.AddTagOp,
        ops_mod.RemoveTagOp,
    ):
        for name, prop in model.model_json_schema()["properties"].items():
            if name == "op":
                continue
            props.setdefault(name, _simplify(prop))
    names = [m for m in ops_mod.PROPOSABLE.json_schema()["$defs"]]
    del names
    props["op"] = {
        "type": "string",
        "enum": [
            "create_item",
            "update_item",
            "move_item",
            "set_quantity",
            "delete_item",
            "create_location",
            "update_location",
            "move_location",
            "archive_location",
            "create_category",
            "update_category",
            "merge_categories",
            "delete_category",
            "add_tag",
            "remove_tag",
        ],
    }
    return {"type": "object", "properties": props, "required": ["op"]}


def _simplify(prop: dict[str, Any]) -> dict[str, Any]:
    if "anyOf" in prop:
        options = [o for o in prop["anyOf"] if o.get("type") != "null"]
        # Decimal = anyOf[number, string] → number
        base = next(
            (o for o in options if o.get("type") == "number"),
            options[0] if options else {"type": "string"},
        )
        out = _simplify(base)
    else:
        out = {k: v for k, v in prop.items() if k in ("type", "enum", "items", "description")}
        if "items" in out:
            out["items"] = _simplify(out["items"])
        if out.get("format") == "uuid":
            out.pop("format")
    if prop.get("description"):
        out["description"] = prop["description"]
    return out


OPERATIONS_HELP = """\
Operace v propose_changes (každá je objekt s polem "op" a jeho parametry):
- create_item: name, [category_path|category_id], [location_path|location_id], quantity, tags, aliases, notes, brand, model, unit, is_consumable
- update_item: item_id + měněná pole (name, notes, brand, model, status, category_path|category_id, aliases, tags, add_tags, remove_tags)
- move_item: item_id, to_location_path|to_location_id, [from_location_id], [quantity]
- set_quantity: item_id, location_id, quantity (přesný počet, 0 = pryč z umístění)
- delete_item: item_id (přesune do koše; vždy vyžaduje potvrzení v aplikaci)
- create_location: name, [parent_path|parent_id], kind, [is_movable]
- update_location: location_id, [name, kind, notes, description]
- move_location: location_id, new_parent_path|new_parent_id | to_root=true
- archive_location: location_id (jen prázdné)
- create_category: name, [parent_path|parent_id]
- update_category: category_id, [name, description, new_parent_path|new_parent_id | to_root]
- merge_categories: source_id, target_id (vyžaduje potvrzení v aplikaci)
- delete_category: category_id, [reassign_to] (vyžaduje potvrzení v aplikaci)
- add_tag / remove_tag: item_id, tag
Cesty (path) jsou seznamy názvů od kořene, např. ["Dům","Garáž","Regál A"]; neexistující se vytvoří."""


def tool_specs(*, can_write: bool, voice_confirm: bool) -> list[ToolSpec]:
    uuid_str = {"type": "string", "description": "UUID"}
    specs = [
        ToolSpec(
            "search_items",
            "Hledá věci (název, alias, tag, štítek, EAN; bez ohledu na diakritiku a překlepy). "
            "Použij vždy, když se uživatel ptá, kde něco je.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "category_id": uuid_str,
                    "location_id": uuid_str,
                    "status": {"type": "string"},
                    "unplaced": {"type": "boolean", "description": "jen věci bez umístění"},
                    "low_stock": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
            },
        ),
        ToolSpec(
            "get_item",
            "Podrobnosti o jedné věci včetně všech umístění.",
            {"type": "object", "properties": {"item_id": uuid_str}, "required": ["item_id"]},
        ),
        ToolSpec(
            "get_location_contents",
            "Co je v umístění (a v jeho podstromu).",
            {
                "type": "object",
                "properties": {"location_id": uuid_str, "recursive": {"type": "boolean"}},
                "required": ["location_id"],
            },
        ),
        ToolSpec(
            "list_locations",
            "Seznam umístění s cestami, id a počty věcí.",
            {
                "type": "object",
                "properties": {
                    "under": {
                        "type": "string",
                        "description": "volitelně část cesty pro zúžení, např. 'Garáž'",
                    }
                },
            },
        ),
        ToolSpec(
            "list_categories",
            "Strom kategorií s id a počty věcí.",
            {"type": "object", "properties": {}},
        ),
        ToolSpec(
            "find_duplicates",
            "Najde věci s podobným názvem (před vytvořením nové).",
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        ),
        ToolSpec(
            "get_item_history",
            "Historie pohybů věci (kam se přesouvala).",
            {
                "type": "object",
                "properties": {"item_id": uuid_str, "limit": {"type": "integer"}},
                "required": ["item_id"],
            },
        ),
        ToolSpec(
            "get_stats",
            "Souhrn: počty věcí, nezařazené, docházející zásoby, končící záruky.",
            {"type": "object", "properties": {}},
        ),
    ]
    if can_write:
        specs.append(
            ToolSpec(
                "propose_changes",
                "Navrhne změny dat (nic se neprovede, dokud je uživatel nepotvrdí – pokud to nastavení "
                "nepovoluje automaticky). Výsledek říká, zda je balíček 'proposed' (čeká na potvrzení) "
                "nebo 'applied'.\n" + OPERATIONS_HELP,
                {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "krátký popis změn pro uživatele",
                        },
                        "operations": {"type": "array", "items": _schema_from_models()},
                    },
                    "required": ["summary", "operations"],
                },
            )
        )
        if voice_confirm:
            specs.append(
                ToolSpec(
                    "confirm_pending_changes",
                    "Použij POUZE když uživatel výslovně odpoví ano/ne na tvou otázku o navržených změnách.",
                    {
                        "type": "object",
                        "properties": {"approve": {"type": "boolean"}},
                        "required": ["approve"],
                    },
                )
            )
    return specs


@dataclass
class ToolRuntime:
    db: Session
    ctx: ActorContext
    user_id: uuid.UUID
    can_write: bool
    conversation_id: uuid.UUID | None = None
    voice: bool = False
    change_sets: list[dict[str, Any]] = field(default_factory=list)

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            handler = getattr(self, f"_t_{name}", None)
            if handler is None:
                raise ValidationFailed(f"Neznámý nástroj „{name}“.")
            return handler(**args)  # type: ignore[no-any-return]
        except DomainError as exc:
            return {"error": exc.message}
        except (TypeError, ValueError) as exc:
            return {"error": f"Neplatné parametry nástroje: {exc}"}

    # --- čtení ---------------------------------------------------------------------------

    def _t_search_items(
        self,
        query: str | None = None,
        category_id: str | None = None,
        location_id: str | None = None,
        status: str | None = None,
        unplaced: bool | None = None,
        low_stock: bool | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        page = search.search_items(
            self.db,
            ItemFilter(
                q=query,
                category_id=uuid.UUID(category_id) if category_id else None,
                location_id=uuid.UUID(location_id) if location_id else None,
                status=status,
                unplaced=unplaced,
                low_stock=low_stock,
                limit=max(1, min(limit, MAX_RESULTS)),
                fuzzy_threshold=float(
                    settings_service.get_value(self.db, "search.fuzzy_threshold")
                ),
            ),
        )
        return {"total": page.total, "items": [compact_item(i) for i in page.items]}

    def _t_get_item(self, item_id: str) -> dict[str, Any]:
        return compact_item(items.get_item_out(self.db, uuid.UUID(item_id)))

    def _t_get_location_contents(self, location_id: str, recursive: bool = True) -> dict[str, Any]:
        rows = locations.contents(self.db, uuid.UUID(location_id), recursive=recursive)
        names = locations.location_full_names(self.db, list({r["location_id"] for r in rows}))
        return {
            "count": len(rows),
            "items": [
                {
                    "item_id": str(r["item_id"]),
                    "label": r["label_code"],
                    "name": r["name"],
                    "quantity": str(r["quantity"]),
                    "unit": r["unit"],
                    "location": names.get(r["location_id"]),
                }
                for r in rows[:100]
            ],
            **({"truncated": True} if len(rows) > 100 else {}),
        }

    def _t_list_locations(self, under: str | None = None) -> dict[str, Any]:
        rows = locations.list_locations(self.db)
        if under:
            needle = under.lower()
            rows = [r for r in rows if needle in (r.full_name or "").lower()]
        return {
            "locations": [
                {"id": str(r.id), "path": r.full_name, "kind": r.kind, "items": r.item_count}
                for r in rows[:200]
            ],
            **({"truncated": True} if len(rows) > 200 else {}),
        }

    def _t_list_categories(self) -> dict[str, Any]:
        return {
            "categories": [
                {"id": str(c.id), "path": c.full_name, "items": c.item_count}
                for c in categories.list_categories(self.db)
            ]
        }

    def _t_find_duplicates(self, name: str) -> dict[str, Any]:
        found = search.find_duplicates(self.db, name)
        return {"similar": [compact_item(i) for i in items.to_out(self.db, found)]}

    def _t_get_item_history(self, item_id: str, limit: int = 10) -> dict[str, Any]:
        moves = items.list_movements(self.db, uuid.UUID(item_id), limit=max(1, min(limit, 30)))
        ids = {m.from_location_id for m in moves} | {m.to_location_id for m in moves}
        names = locations.location_full_names(self.db, [i for i in ids if i])
        return {
            "movements": [
                {
                    "kind": m.kind,
                    "at": m.moved_at.isoformat(),
                    "from": names.get(m.from_location_id) if m.from_location_id else None,
                    "to": names.get(m.to_location_id) if m.to_location_id else None,
                    "quantity": str(m.quantity) if m.quantity else None,
                    "source": m.source,
                }
                for m in moves
            ]
        }

    def _t_get_stats(self) -> dict[str, Any]:
        d = stats.dashboard(self.db)
        return {
            "counts": d["counts"],
            "low_stock": [i.name for i in d["low_stock"]],
            "warranty_soon": [i.name for i in d["warranty_soon"]],
            "expiring_soon": [i.name for i in d["expiring_soon"]],
        }

    # --- zápis (jen návrh) -----------------------------------------------------------------

    def _t_propose_changes(self, summary: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.can_write:
            raise ValidationFailed("Uživatel nemá oprávnění měnit data.")
        cs = changesets.propose(
            self.db,
            self.ctx,
            summary=summary,
            operations=operations,
            conversation_id=self.conversation_id,
        )
        rows = changesets.operations(self.db, cs.id)
        auto = changesets.can_auto_apply(self.db, rows, user_id=self.user_id)
        if auto:
            cs = changesets.apply_change_set(self.db, self.ctx, cs.id, auto=True)
        described = changesets.describe_change_set(self.db, cs)
        self.change_sets.append(described)
        out: dict[str, Any] = {
            "change_set_id": described["id"],
            "status": cs.status,
            "operations": [o["description"] for o in described["operations"]],
        }
        if cs.status == "failed":
            out["error"] = next(
                (o["error"] for o in described["operations"] if o["error"]), "chyba"
            )
        elif cs.status == "proposed":
            out["note"] = (
                "Změny čekají na potvrzení uživatele. "
                + (
                    "Zeptej se ho slovy, zda je mají provést. "
                    if self.voice
                    else "Uživatel je potvrdí tlačítkem v aplikaci. "
                )
                + (
                    "Mazání a slučování kategorií lze potvrdit jen v aplikaci."
                    if described["needs_ui_confirmation"]
                    else ""
                )
            )
        return out

    def _t_confirm_pending_changes(self, approve: bool) -> dict[str, Any]:
        """Hlasové potvrzení: smí jen balíčky navržené v této konverzaci a bez mazání/slučování."""
        if not (self.voice and self.can_write):
            raise ValidationFailed("Potvrzení slovem není povoleno.")
        pending = [
            cs
            for cs in changesets.list_change_sets(self.db, user_id=self.user_id, status="proposed")
            if cs.conversation_id == self.conversation_id
        ]
        if not pending:
            return {"result": "Není co potvrdit."}
        cs = pending[0]
        rows = changesets.operations(self.db, cs.id)
        if approve and changesets.has_never_auto(rows):
            return {"error": "Tuto změnu lze potvrdit jen v aplikaci."}
        done: AiChangeSet = (
            changesets.apply_change_set(self.db, self.ctx, cs.id)
            if approve
            else changesets.reject_change_set(self.db, self.ctx, cs.id)
        )
        described = changesets.describe_change_set(self.db, done)
        self.change_sets.append(described)
        return {"status": done.status, "summary": done.summary}


def tool_result_text(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)


_ = (BaseModel, ItemPlacement)
