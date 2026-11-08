# Nasazení na Proxmox (LXC + Docker Compose)

Cílový stav: jeden LXC kontejner `domovnik` (Debian 12, bez privilegií, `nesting=1`), uvnitř Docker Compose se službami **db** (PostgreSQL 16 + pgvector), **api** (FastAPI) a **web** (Caddy: statický web + reverzní proxy). Data (databáze, fotky, zálohy) leží na samostatném disku `/data`.

## 1. Vytvoření kontejneru (na Proxmox hostu)
Skripty jsou v `deploy/proxmox/`. Na hostu jako root:

```bash
# zkopíruj create-lxc.sh a bootstrap.sh na host (nebo naklonuj repozitář), potom:
CTID=200 STORAGE=ssdpool DATA_SIZE=100 ./create-lxc.sh
```
Výchozí hodnoty odpovídají tvému prostředí: úložiště `ssdpool` (LVM-thin), 4 vCPU, 8 GB RAM, rootfs 32 GB, `/data` 100 GB (`backup=1` → je součástí zálohy `vzdump`/PBS). Pevná IP: `IP=192.168.1.50/24 GW=192.168.1.1`.

## 2. Instalace aplikace (uvnitř kontejneru)
```bash
pct exec 200 -- env REPO_URL=https://github.com/<uživatel>/Domovnik.git DOMOVNIK_HOST=domovnik.lan /root/bootstrap.sh
```
Skript nainstaluje Docker, nastaví firewall (22, 80, 443, 8080), naklonuje repozitář do `/opt/domovnik`, vygeneruje `deploy/.env` s tajemstvími (**zálohuj si ho** – `SECRET_KEY` šifruje API klíče v databázi), nainstaluje denní zálohu databáze a spustí `docker compose up -d --build`. První otevření webu vytvoří administrátora.

## 3. HTTPS (nutné pro kameru a mikrofon v telefonu)
**A) Dnes – interní certifikát (výchozí `CADDYFILE=/etc/caddy/Caddyfile`).** Caddy vystaví certifikát pro `DOMOVNIK_HOST`. Kořenový certifikát stáhni a nainstaluj do obou telefonů:
```bash
docker compose -f deploy/compose.prod.yml --env-file deploy/.env cp web:/data/caddy/pki/authorities/local/root.crt ./domovnik-root.crt
```
Android: *Nastavení → Zabezpečení → Šifrování a přihlašovací údaje → Instalovat certifikát → CA certifikát*. Název `DOMOVNIK_HOST` musí být dostupný z telefonu (DNS v routeru / Pi-hole / záznam ve VPN).

**B) Později – Nginx Proxy Manager + Let's Encrypt.** V `deploy/.env` nastav `CADDYFILE=/etc/caddy/Caddyfile.http`, `HTTP_PORT=8081`, `HTTPS_PORT=8444` (aby nekolidovaly) a v NPM vytvoř Proxy Host na `http://<IP-LXC>:8080` s certifikátem (ideálně DNS-01, protože aplikace není vystavená do internetu). V NPM zapni **WebSockets**, v *Advanced* přidej:
```
proxy_buffering off;
proxy_read_timeout 300s;
client_max_body_size 50m;
```
Přístup zvenčí řeš **VPN** (WireGuard/Tailscale), porty nevystavuj do internetu.

## 4. Nastavení po spuštění
1. Vytvoř administrátora (první otevření). Další lidi přidej v *Nastavení → Uživatelé*.
2. *Nastavení → AI asistent*: vlož Gemini API klíč, případně záložního providera.
3. (volitelně) naplň ukázkovými daty jen na zkoušku: `docker compose … exec api domovnik seed` – **ne** na ostré instanci.

## 5. Zálohy
| Co | Jak |
|---|---|
| Celý kontejner (systém + `/data` vč. fotek) | `vzdump` do **PBS `PBSprodesk`** – naplánuj denní úlohu pro CT 200 (Datacenter → Backup). Disk `/data` má `backup=1`. |
| Databáze (konzistentní dump) | cron v kontejneru 03:30 → `/data/backups/domovnik-*.dump` (rotace 14 dní, skript `deploy/backup/backup.sh`) |
| Test obnovy | `deploy/backup/restore-test.sh` – načte poslední dump do dočasné DB a ověří data (spouštěj občas ručně / z cronu) |
| Obnova DB | `deploy/backup/restore.sh /data/backups/domovnik-….dump` |
| Tajemství | **ulož si `deploy/.env` mimo server** (správce hesel). Bez `SECRET_KEY` nejdou dešifrovat API klíče v nastavení. |

Doporučení: nastav PBS tak, aby pre-backup hook zavolal `backup.sh` (dump se pak vždy nachází uvnitř snapshotu) nebo ponech cron a spoléhej na konzistenci dumpu.

## 6. Aktualizace
```bash
cd /opt/domovnik && git pull --ff-only
docker compose -f deploy/compose.prod.yml --env-file deploy/.env up -d --build
```
Migrace databáze se při startu API spustí automaticky (`entrypoint.sh`). Před větší aktualizací udělej snapshot kontejneru v Proxmoxu nebo `domovnik-backup`.

## 7. Provozní příkazy
```bash
cd /opt/domovnik
docker compose -f deploy/compose.prod.yml --env-file deploy/.env ps
docker compose -f deploy/compose.prod.yml --env-file deploy/.env logs -f api
docker compose -f deploy/compose.prod.yml --env-file deploy/.env exec api domovnik create-admin --username jmeno   # nový admin (např. při zapomenutém hesle)
curl -s http://127.0.0.1:8080/api/v1/health/ready      # zdraví (přes Caddy)
```

## 8. Bezpečnost (shrnutí)
HTTPS všude, cookie `Secure`+`HttpOnly`+`SameSite=Lax`, CSRF hlavička, API běží pod uživatelem bez práv roota, databáze není vystavená mimo kontejnery, v produkci API odmítne start s výchozím `SECRET_KEY` nebo vývojovým heslem DB. Soubory se při nahrání vždy re-enkódují (bez skrytých dat a GPS).

## 9. Řešení potíží
- **Kamera/mikrofon nefunguje** – stránka není na HTTPS, nebo telefon nedůvěřuje certifikátu (viz 3A).
- **Chat se „zasekne“** – za NPM chybí `proxy_buffering off` / WebSockets.
- **Docker v LXC nejde spustit** – kontejner musí mít `nesting=1,keyctl=1` a být po změně restartován.
- **API nenastartuje** – `docker compose … logs api` (typicky chybějící `SECRET_KEY`/`POSTGRES_PASSWORD`).
- **Nahrání fotky vrací chybu 500 (`PermissionError: /data/files/…`)** – složka s fotkami musí patřit uživateli API (UID 10001): `chown -R 10001:10001 /data/files` (uvnitř LXC). Nové instalace to řeší `bootstrap.sh`.
