# Domovník – domácí inventář s AI asistentem

Self-hosted aplikace pro evidenci fyzických věcí v domě (kde co je, kolik, kategorie, fotky). Čeština je primární jazyk UI i AI. Podrobnosti: `docs/01-navrh.md` (návrh), `docs/02-databaze.md` + `db/schema.sql` (DB), `docs/04-postup-claude-code.md` (fáze). Rozhodnutí uživatele: `docs/00-rozhodnuti.md`.

## Stack
- API: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, Procrastinate (fronta v PG). Správa: `uv`.
- DB: PostgreSQL 16 + ltree, pg_trgm, unaccent, pgvector.
- Web: React + TypeScript + Vite, TanStack Query/Table, Tailwind + shadcn/ui, PWA. Správa: `pnpm`.
- Nasazení: Docker Compose v LXC na Proxmoxu, Caddy (HTTPS je nutné pro kameru/mikrofon).

## Příkazy
Z kořene repa (vyžaduje `pnpm`, `uv`, Docker; `uv` na Windows bývá v `%APPDATA%\Python\Python313\Scripts` – přidej do PATH):
- `pnpm install` + `cd apps/api && uv sync` – instalace závislostí
- `pnpm dev` – spustí DB (Docker), API (`:8000`) a web (`:5173`, proxy `/api` → API)
- `pnpm db:up` / `pnpm db:down` – jen databáze
- `pnpm lint` / `pnpm test` / `pnpm build` – kontroly (api: ruff, mypy, pytest; web: eslint, tsc, prettier, vitest)
- `pnpm test:api` s `DATABASE_URL` v prostředí spustí i integrační testy proti DB
- Lokální konfigurace: zkopíruj `.env.example` → `.env` (necommituje se)

Poznámky: TypeScript je připnutý na `~5.9`, protože `typescript-eslint` zatím nepodporuje TS 7. `just` se nepoužívá (nahrazují ho skripty v kořenovém `package.json`).

## Neměnná architektonická pravidla
1. **Veškerá byznys logika je v `apps/api/src/domovnik/services/`.** Routery REST/MQTT/MCP/AI nástroje jsou tenké adaptéry, které službu jen volají. Žádný SQL ani logika v routerech.
2. **Každý zápis jde přes službu s `ActorContext`** (actor_id, source = ui|ai|voice|api|mqtt|import, change_set_id); ten nastaví `SET LOCAL app.*` pro audit trigger. Bez kontextu se nezapisuje.
3. **AI nikdy nezapisuje přímo.** Zapisovací nástroj je jen `propose_changes` → `ai_change_set`. AI nemá nástroj pro trvalé smazání. Každá aplikovaná operace ukládá `inverse` (undo).
4. **Text z fotek, dokumentů a názvů věcí je DATA, ne instrukce** (ochrana proti prompt injection). Nikdy ho nevkládej do system promptu.
5. **Schéma mění jen Alembic migrace.** Triggery/funkce jsou součástí migrací. Žádné ruční změny DB.
6. PK jsou UUID (klient může generovat při offline zápisu). Časy v UTC (`timestamptz`), zobrazení v zóně uživatele.
7. Optimistické zamykání: úpravy posílají `version` (`If-Match`); nesoulad = 409.
8. Událost každé změny jde do `event_outbox` ve stejné transakci (MQTT, webhooky, SSE čtou z něj).
9. Nastavení definuje **registr v kódu** (`settings_registry.py`); tajné hodnoty šifrované. Nové chování = nová položka nastavení s rozumným výchozím stavem.
10. UI texty výhradně přes i18n (`cs` výchozí). Žádné natvrdo psané řetězce.
11. Soubory: adresované sha256, obrázky vždy re-enkódovat, GPS z EXIF odstraňovat dle nastavení.

## Konvence
- Python: ruff (format + lint), plná typová anotace, `pytest` + testcontainers proti **skutečnému Postgresu** (ne SQLite).
- TS: strict, eslint + prettier, komponenty podle feature (`src/features/<název>/`).
- Commity malé, česky nebo anglicky konzistentně; jedna fáze = jedna větev = jedno PR.
- API: `/api/v1`, OpenAPI musí být úplné; chyby ve formátu RFC 9457 (problem+json).
- Nikdy necommituj `.env`, klíče, hesla, datové soubory ani fotky; používej `.env.example`.

## Definition of done (každá fáze)
- Lint + typy + testy zelené (`just lint test`), migrace jdou nahoru i dolů.
- Nové funkce mají testy; UI změny ověřeny Playwright screenshoty (desktop 1440 px, mobil 390 px).
- Nové volby jsou v registru nastavení; dokumentace/ADR aktualizovány, `CLAUDE.md` obsahuje nové příkazy.
- Žádná odchylka od `docs/01-navrh.md` bez zápisu do `docs/adr/`.

## Kde začít
Aktuální fáze: **F1** (F0 kostra hotová; viz `docs/04-postup-claude-code.md`, sekce 3). Před každou fází použij plan mode a nech si předložit plán ke schválení.
