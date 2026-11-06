# Odložené otázky (k doladění po návratu)

Během samostatné práce jsem se neptal; kde bylo potřeba rozhodnout, zvolil jsem rozumný výchozí stav (uvedeno v závorce). Stačí potvrdit nebo změnit.

## Nutné k plnému fungování
1. **Gemini API klíč** – bez něj AI asistent a čtení fotek nefungují (do té doby jde jen vývojový demo režim `DOMOVNIK_FAKE_AI=1`). Zadej v *Nastavení → AI asistent → Gemini API klíč* (uloží se šifrovaně). *(Výchozí modely `gemini-2.5-flash`; názvy modelů a limity free tieru ověř v dokumentaci Google – mění se.)*
2. **Záložní provider** (Claude / OpenAI-kompatibilní) – chceš ho nastavit? *(Výchozí: žádný.)*
3. **Úroveň důvěry v AI změny** – *(výchozí „ptát se vždy“; později lze „drobnosti automaticky“. Mazání a slučování kategorií AI nikdy neprovede bez potvrzení v aplikaci.)*
4. **HTTPS pro mobil** – kamera a mikrofon fungují jen přes HTTPS. *(Plán: Caddy s interním certifikátem do doby, než bude doména s Let's Encrypt přes Nginx Proxy Manager.)* Potřebuji: název domény, nebo zda máš zájem o interní CA.

## Infrastruktura (až při nasazení na Proxmox)
5. Přesné parametry LXC: potvrzení `ssdpool` (LVM-thin), 4 vCPU / 8 GB RAM, `/data` 100 GB; PBS úloha `PBSprodesk`.
6. Offsite záloha (restic) – kam? *(Výchozí: jen PBS.)*
7. Přihlášení druhé osoby (přítelkyně): *(role „člen“, vlastní účet; účty zakládá administrátor v Nastavení → Uživatelé.)*

## Home Assistant a hlas (F9 / F8)
8. Verze HAOS a to, zda tvůj HA umí MCP klienta (přenos SSE vs. streamable HTTP) – podle toho zvolím napojení; záložní cesta je REST `POST /api/v1/ai/ask`.
9. **Hlas v aplikaci:** ve v1 je rozpoznávání a čtení v prohlížeči (Web Speech API). Chceš lokální Whisper + Piper (kvalita češtiny, offline)? Stojí to ~2–4 GB RAM navíc. *(Výchozí: nejdřív prohlížeč, lokální engine jako volitelný krok.)*
10. **MQTT** – zatím vypnuté (podle rozhodnutí). Až bude potřeba: adresa brokeru, TLS, uživatel.

## Data a pravidla domácnosti
11. **Pravidla pro AI** (Nastavení → AI → „Vlastní pravidla domácnosti“) – např. „Kabely vždy do krabice Kabely“, „Kategorie česky, jednotné číslo“. Prázdné = žádná.
12. **Struktura domu:** ukázková data (`pnpm db:seed`) jsou jen pro vývoj – skutečné místnosti/police založíš ručně, nebo je nechej navrhnout asistentem z fotek.
13. **Viditelnost věcí mezi členy:** *(výchozí: vše sdílené; pole „vlastník“ je připravené, ale nefiltruje.)*
14. **Doba uchování:** koš 90 dní, historie konverzací AI 90 dní, audit 2 roky – *(nastavitelné; mazací úlohy zatím neběží, bude potřeba worker.)*

## Fotky a soukromí
15. Free tier AI může vstupy použít ke zlepšování služeb (akceptováno). GPS se z fotek odstraňuje *(výchozí zapnuto)*.
16. Ukládat i **originály fotek**? *(Výchozí: ne, jen zmenšené na 2048 px; přepínač `photos.keep_original`.)*

## Štítky
17. Jaké **archy samolepek** máš (rozměry, počet na A4)? *(Výchozí tři formáty: 3×8, 2×5, 4×12 + možnost začít od N-tého políčka.)*
18. Chceš po sobě použít i **NFC tagy** nebo jen QR? *(Jen QR.)*

## Co zatím chybí (naplánováno, bez práce vyžadující tvé rozhodnutí)
- Worker na pozadí (fronta úloh): úklid koše, připomínky záruk/expirací, embeddings, zálohy.
- Sémantické hledání (embeddings) – schéma je připravené (`item_embeddings`), zbývá napojit model.
- Hlasový engine na serveru (Whisper/Piper), MQTT a Home Assistant integrace (MCP server).
- Import/export CSV/XLSX, webhooky, MCP server.
- Produkční nasazení (Docker Compose, LXC skript, zálohy) – viz `docs/01-navrh.md` §10.
