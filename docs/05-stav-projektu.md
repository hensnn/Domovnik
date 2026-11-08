# Stav projektu (k 2026-11-06)

## Hotovo
Vše je sloučené ve větvi **`feat/integrace`** (obsahuje všechny níže uvedené části; ostatní větve jsou jen průběžné kroky).

| Část | Obsah |
|---|---|
| F0–F2 | Kostra repa, Alembic, služby (umístění, kategorie, věci, tagy), audit, outbox, auth (relace + tokeny), registr nastavení, REST API, hledání (bez diakritiky, překlepy, aliasy), seed, CLI, SSE |
| F3 | Webové UI: přehled, věci (tabulka/karty, filtry, hromadné akce, detail), umístění, kategorie, nastavení, účet, uživatelé, Ctrl+K |
| F4 | Fotky a dokumenty: validace obsahu, re-enkódování, GPS pryč, náhledy, dedupe, galerie, nahrávání z mobilu |
| F6 | AI asistent: Gemini / Claude / OpenAI-kompatibilní, záložní řetěz, nástroje, balíčky změn s potvrzením a vrácením zpět, chat (SSE), `/ai/ask`, hlas v prohlížeči |
| F7 | Čtení fotek AI: analýza, duplicity, návrh umístění, revize s rámečky, ořezy, plán uložení; web „Přidat z fotky“ |
| F5b | Štítky jako PDF (QR, A4 3×8 / 2×5 / 4×12), skenování QR, „Jsem tady“, inventura, PWA (manifest, service worker, offline čtení) |
| F9 (část) | Import / export CSV (dry-run, mapování, české výchozí pro Excel) |
| F10 | Produkční nasazení: Docker Compose, Caddy, skripty pro LXC, zálohy, test produkčního stacku (`docs/06-nasazeni.md`) |
| + | Sémantické hledání (embeddings, hybridní s fulltextem) |
| + | Hledání podle druhu umístění a rozšířené filtry, správa tagů (barva, sloučení), přetahování umístění, zvětšení fotky při kontrole, asistent v panelu u umístění a kategorií |
| + | **Knihovna znalostí AI** (`/knowledge`, tabulka `ai_knowledge`, migrace 0006): pravidla uspořádání a zvyky domácnosti spravuje admin, AI je dostává v promptu (limit `ai.knowledge_max_chars`) a zbytek hledá nástrojem `search_knowledge`; AI nové pravidlo jen navrhne (`add_knowledge`, vždy s potvrzením, od ne-admina vypnuté do schválení) |
| + | Výchozí umístění z „Jsem tady“: nová věc / přesun bez uvedeného místa použije tuto pozici, asistent se neptá (jen výslovné jiné místo má přednost; věc bez místa jen s `unplaced`) |

| + | Instalace do telefonu (PWA): tlačítko „Nainstalovat aplikaci“ (postranní menu, Více), pruh na telefonu, návod pro Android / iPhone / počítač; vyžaduje HTTPS s důvěryhodným certifikátem |
| + | Duplikování věcí (předvyplněný formulář), umístění a kategorií (`POST /locations/{id}/duplicate`, `POST /categories/{id}/duplicate`; kopíruje se struktura, ne věci a fotky) |

| + | Asistent při kontrole nálezů z fotky (`POST /photos/analyses/{id}/refine`): upravuje jen koncept (přijmout / zamítnout / sloučit, názvy, množství, kategorie, umístění vč. nového), každou úpravu jde vrátit, věci se zapíšou až závěrečným potvrzením |

Testy: backend 178, web 123 (vše zelené, lint a typy také).

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
- Sémantické hledání je zapojené, ale nastaví se až zadáním modelu pro embeddings (Nastavení → AI) a spuštěním `POST /ai/embeddings/sync`; do té doby hledá fulltext + trigramy + aliasy.
- Čtení fotek posílá jednu zmenšenou fotku (bez dlaždic 2×2) – u velmi husté police může minout drobné věci.
- Bez workeru: náhledy a analýzy běží ve vláknech API, úklidové a připomínkové úlohy zatím neexistují.
- Offline fronta zápisů (vytvoření/přesun bez spojení) není hotová; backend je připravený (klientské `id`). Offline lze zatím jen číst uložená data.
- Service worker a kamera (QR) nešlo v testovacím prohlížeči ověřit – vyzkoušej na telefonu přes HTTPS.
- Font DejaVu v PDF štítcích: porovnej text licence (`assets/fonts/LICENSE-DejaVu.txt`) s oficiálním zněním.
- Čtení fotek proti skutečnému Gemini zatím nikdo nezkoušel (jen falešný poskytovatel a testy).
- Dev tip: relační cookie je sdílená mezi porty `localhost`; při souběžných dev serverech se session navzájem přepisují.
- Optimistické zamykání: změna primární fotky zvyšuje `version` věci, UI proto věc po nahrání fotek načítá znovu.
- Zbývá: MQTT (zatím vypnuté dle rozhodnutí), Home Assistant přes MCP, webhooky, hlasový engine na serveru (Whisper/Piper), worker na pozadí, skutečné nasazení na Proxmox – viz `docs/04-postup-claude-code.md` a `docs/odlozene-otazky.md`.
