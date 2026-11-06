# Stav projektu (k 2026-11-06)

## Hotovo
| Fáze | Obsah | Větev |
|---|---|---|
| F0 | Kostra monorepa, DB v Dockeru, CI | `feat/f0-kostra-2` |
| F1 | Alembic migrace, ORM, služby (umístění, kategorie, věci, tagy), audit, outbox, auth (relace + tokeny), registr nastavení | `feat/f1-jadro` |
| F2 | REST API, hledání (bez diakritiky, překlepy, aliasy), seed, CLI, SSE | `feat/f2-api` |
| F3 | Webové UI (přehled, věci, umístění, kategorie, nastavení, účet, uživatelé) | `feat/f3-web` |
| F4 (backend) | Nahrávání fotek a dokumentů, náhledy, dedupe, vazby | `feat/f4-fotky` (sloučeno do F6) |
| F6 | AI asistent: poskytovatelé, nástroje, balíčky změn s undo, chat (SSE), `/ai/ask` | `feat/f6-ai` |
| F7 (backend) | Čtení fotek AI, duplicity, návrh umístění, revize, plán uložení | `feat/f7-ai-fotky` |

Větve na sobě stavějí (každá obsahuje předchozí). Poslední (nejúplnější) je `feat/f7-ai-fotky`; webové UI pro chat/fotky/revizi a štítky/QR/inventuru/PWA vzniká paralelně ve větvích `feat/web-ai-fotky` a `feat/f5b-stitky` (stav viz konec dokumentu).

## Jak to spustit (vývoj)
```bash
cp .env.example .env
pnpm install
cd apps/api && uv sync && cd ../..
pnpm db:up && pnpm db:migrate     # PostgreSQL v Dockeru + migrace
pnpm db:seed                      # ukázková data (jen vývoj)
pnpm dev:api                      # API :8000
pnpm dev:web                      # web :5173
```
První otevření webu nabídne vytvoření administrátora. Bez API klíče lze AI vyzkoušet v demo režimu: `DOMOVNIK_FAKE_AI=1 pnpm dev:api`.

Kontroly: `pnpm lint`, `pnpm test` (API testy vyžadují běžící DB; vytvářejí si vlastní databázi `domovnik_test`, název lze změnit proměnnou `DOMOVNIK_TEST_DB`).

## Jak vyzkoušet AI s Gemini
1. V Google AI Studio vytvoř API klíč, v aplikaci *Nastavení → AI asistent* ho vlož (uloží se šifrovaně).
2. *Asistent* → „Kde mám kladivo?“, „Přesuň kladivo do dílny“ (navrhne změnu, potvrdíš tlačítkem, jde vrátit).
3. *Přidat z fotky* → vyfoť polici, zkontroluj návrhy, ulož.

## Klíčová rozhodnutí implementace
- **Service layer je jediná logika**: UI, REST, AI i budoucí MQTT volají stejné služby; audit zajišťuje DB trigger (`SET LOCAL app.*`), takže pokrývá všechny kanály.
- **AI nezapisuje přímo**: jen balíčky změn (`ai_change_sets`) s náhledem, atomickým provedením a inverzními operacemi (undo). Mazání, sloučení kategorií a smazání kategorie AI nikdy nespustí bez potvrzení v aplikaci; hlasem lze potvrdit jen neriziková změna.
- **Poskytovatelé AI** jsou vyměnitelní (Gemini / Claude / OpenAI-kompatibilní) se záložním řetězem a lokálními limity (minuta/den) kvůli free tieru.
- **Text z fotek a názvů je data, ne instrukce** (ochrana proti prompt injection; testováno).
- **Fotky**: obsah se ověřuje podle magic bytes, vždy se re-enkódují, GPS se odstraňuje, dedupe přes SHA-256 (viz `docs/adr/0001-uloziste-souboru.md`).

## Známá omezení a otevřené body
- Hledání je fulltext + trigramy + aliasy; sémantické hledání (embeddings) zatím není zapojeno.
- Čtení fotek posílá jednu zmenšenou fotku (bez dlaždic 2×2) – u velmi husté police může minout drobné věci.
- Bez workeru: náhledy a analýzy běží ve vláknech API, úklidové a připomínkové úlohy zatím neexistují.
- Optimistické zamykání: změna primární fotky zvyšuje `version` věci, UI proto věc po nahrání fotek načítá znovu.
- Produkční nasazení (Compose, LXC skript, zálohy) a integrace (MQTT, HA/MCP, CSV) zbývají – viz `docs/04-postup-claude-code.md`.
