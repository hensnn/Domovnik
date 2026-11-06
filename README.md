# Domovník – návrh domácího inventáře s AI

| Soubor | Obsah |
|---|---|
| [docs/00-rozhodnuti.md](docs/00-rozhodnuti.md) | Tvoje odpovědi a z nich odvozená rozhodnutí + zbývající otevřené otázky |
| [docs/05-stav-projektu.md](docs/05-stav-projektu.md) | **Aktuální stav**: co je hotové, jak spustit, jak vyzkoušet AI, omezení |
| [docs/odlozene-otazky.md](docs/odlozene-otazky.md) | Otázky odložené na později (s výchozími hodnotami) |
| [docs/01-navrh.md](docs/01-navrh.md) | Hlavní návrh: stack, architektura, moduly, AI asistent, hlas, integrace (CSV/MQTT/API/MCP), nastavení, UI, **nasazení na Proxmox LXC**, bezpečnost, **nedostatky zadání**, **další funkce**, roadmapa |
| [docs/02-databaze.md](docs/02-databaze.md) | Návrh databáze, ER diagram, klíčová rozhodnutí |
| [db/schema.sql](db/schema.sql) | Referenční schéma PostgreSQL 16 (ověřeno načtením + smoke testem) |
| [docs/03-otazky.md](docs/03-otazky.md) | 70 doplňujících otázek s výchozími doporučeními |
| [docs/04-postup-claude-code.md](docs/04-postup-claude-code.md) | Postup pro Claude Code: příprava, struktura repa, fáze F0–F10 s hotovými prompty |
| [CLAUDE.md](CLAUDE.md) | Šablona pro kořen repozitáře – trvalé instrukce pro Claude Code |

## Rychlý start (vývoj)
```bash
cp .env.example .env
pnpm install
cd apps/api && uv sync && cd ../..
pnpm dev        # DB (Docker) + API :8000 + web :5173
pnpm lint && pnpm test
```
Stav: **F0 hotová** (kostra, health endpointy, DB s pgvector, CI). Další: **F1** – databáze, doména, auth, nastavení.
