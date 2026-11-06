# Rozhodnutí uživatele (zdroj pravdy pro implementaci)

Stav k 2026-11-06. Odpovědi na klíčové otázky z `03-otazky.md`; co zde není, platí výchozí doporučení z tohoto dokumentu.

| # | Rozhodnutí | Důsledek pro návrh |
|---|---|---|
| 1 | Rozsah: **tisíce** věcí | PostgreSQL 16 potvrzen; bez partitioningu a speciálního ladění |
| 2 | AI: **free tier (Gemini a další), výběr providera v nastavení**, případně později placené klíče. **Fotky smí do cloudu** (nejsou citlivé) | Multi-provider abstrakce; Gemini jako výchozí; fronta s omezením rychlosti, počítadlo kvót a fallback na jiného providera; EXIF/GPS se i tak odstraňuje (výchozí) |
| 3 | Uživatelé: **jen členové domácnosti**, přístup zvenčí **přes VPN** | Žádné vystavení do internetu; jednoduché role (admin/člen/čtenář); HTTPS interní |
| 4 | Obsah: elektronika, nábytek, nádobí, „všechno možné“ | Obecné kategorie + vlastní pole; AI navrhuje strom kategorií z dat; spotřebák i unikáty |
| 5 | QR štítky **volitelné**, tiskárna **obyčejná** | QR není podmínkou; tisk jen přes PDF (A4 arch samolepek / běžný papír) |
| 6 | Fotky: **všechny scénáře** (jednotlivé věci, hromady, police, místa) | Plná pipeline z `01-navrh.md` §5.3 včetně dlaždic a ořezů |
| 7 | **Mobil primárně**; možnost **AI na reproduktoru přes Home Assistant** | PWA je hlavní klient; pro reproduktor integrace s HA (viz `01-navrh.md` §7.4) |
| 8 | **MQTT ano** | Dvousměrné MQTT + HA Discovery; parametry brokeru v nastavení |
| 9 | Zdroje: **16 GB RAM**, ~20 GB disk, **PBS, doména, VPN** k dispozici | Lokální Whisper `medium` + Piper se vejdou; lokální LLM se nepočítá. ⚠ Disk 20 GB je málo na fotky – viz otevřené otázky |
| 10 | Existující data: **žádná** | Import (CSV) až později; plnění databáze přes AI a fotky |
| 11 | Rozsah v1: **dle kvality aplikace; AI pro naplnění databáze je primární** | Pořadí fází upraveno: AI čtení fotek hned po základní správě a mobilním vstupu |

## Odvozená rozhodnutí
- **Výchozí AI provider = Gemini (free tier)**, druhý v pořadí lze nastavit (Claude, OpenAI-kompatibilní, Ollama). Modely se vybírají v nastavení zvlášť pro chat / vision / embeddings; konkrétní názvy modelů a limity free tieru se ověří při implementaci (mění se).
- **Free tier a soukromí:** u bezplatných cloudových API mohou poskytovatelé použít vstupy ke zlepšování služeb. Uživatel to akceptoval (fotky nejsou citlivé); přesto zůstane v nastavení přepínač „Povolit cloud“ a odstraňování GPS.
- **Embeddings:** výchozí cloudové (zdarma/levné) nebo lokální `bge-m3`/`multilingual-e5` – dimenze 1024 v DB zůstává; rozhodne se ve F6 podle dostupnosti.
- **STT/TTS v aplikaci** slouží mobilu. **Reproduktor obsluhuje Home Assistant** svým Assist pipeline; aplikace mu dodává „mozek“ přes MCP nebo REST.
- **Tisk štítků:** jen PDF (QR + kód + název), žádná integrace tiskárny ve v1.
- **Přístup:** LAN + VPN, HTTPS přes doménu s DNS-01 certifikátem (bez vystavení portů) nebo `tls internal`.

## Další odpovědi (2. kolo)

| Téma | Odpověď | Důsledek |
|---|---|---|
| Disk | Prostor není problém, uživatel se přizpůsobí doporučení | LXC: rootfs 32 GB + samostatný `/data` 100 GB (thin, lze zvětšit) |
| Telefon | **Android** | PWA je plnohodnotná: Web Push, mikrofon, kamera, `BarcodeDetector` v Chrome; nativní appka není potřeba |
| Home Assistant | **HAOS**, satelit **ESP (Echo)**, **Gemini integrace** v HA | Reproduktorová cesta přes MCP/REST (viz `01-navrh.md` §7.4); Gemini agent v HA použije nástroje Domovníku. Kompatibilitu MCP přenosu (SSE vs. streamable HTTP) ověřit proti verzi HA při F9 |
| Gemini | Klíč uživatel připraví; **záložní provider se bude hodit** | Klíč se zadává v nastavení aplikace (šifrovaně), nikdy do chatu/repa; záložní řetěz je od začátku součást F6 |
| Úložiště Proxmoxu | **LVM-thin (`ssdpool`)** pro kontejnery, `local` (directory), **PBS (`PBSprodesk`)** | Žádný problém s Dockerem v LXC (ext4 rootfs, ne ZFS); `vzdump` snapshot na LVM-thin → PBS (inkrementální, deduplikované) |
| MQTT | **Ano** (broker v HA předpokládán) | Údaje se zadají v nastavení až při F9 |
| Uživatelé | **2 lidé** (uživatel + partnerka), účet pro každého | Role admin + člen; jednoduché vlastnictví věcí volitelné |

## Další odpovědi (3. kolo)

| Téma | Odpověď | Důsledek |
|---|---|---|
| Satelit | ESPHome zařízení `echos3r` (board `esp32s3box`, framework `esp-idf`), tj. M5Stack AtomS3R + Echo Base | Standardní ESPHome voice satelit → Assist pipeline v HA; Domovník s ním komunikuje jen nepřímo přes HA (MCP/REST). Nic na satelitu se nemění |
| Doména / certifikát | **V budoucnu**, Let's Encrypt přes **Nginx Proxy Manager** (NPM) | Aplikace nesmí vyžadovat vlastní Caddy: reverzní proxy je volitelný profil. Do doby, než doména bude, přechodné řešení s interní CA (viz níže) |
| MQTT | **Zatím neřešit**, jen možnost připojení později | MQTT je ve v1 vypnuté (výchozí `enabled=false`); implementace F9 se odloží, schéma (`event_outbox`) zůstává |

**Přechodné HTTPS (než bude doména):** Chrome na Androidu povolí kameru a mikrofon jen na zabezpečeném původu. Proto se v LXC spustí Caddy s `tls internal` a kořenový certifikát se jednorázově nainstaluje do obou telefonů. Až bude doména, certifikát vydá NPM (Let's Encrypt, ideálně DNS-01, protože aplikace není vystavená do internetu) a Caddy profil se vypne.

**Požadavky na NPM (platí i pro budoucí nastavení):** zapnout WebSockets, pro SSE vypnout `proxy_buffering`, zvýšit `client_max_body_size` (nahrávání fotek, např. 50 MB), dlouhé `proxy_read_timeout` (streamování odpovědí AI), předávat `X-Forwarded-*` hlavičky; aplikace je musí respektovat (`--proxy-headers`, nastavení důvěryhodných proxy).

## Zbývá doladit (neblokuje start)
1. Verze HAOS (kvůli podpoře MCP klienta a typu přenosu) – až před integrací s HA.
2. Konkrétní doména a způsob ověření u Let's Encrypt – až při přechodu z interní CA.
3. Adresa a TLS MQTT brokeru – až se bude MQTT zapínat.
