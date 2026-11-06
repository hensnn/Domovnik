#!/usr/bin/env bash
# Příprava prostředí UVNITŘ LXC (Debian 12): Docker, firewall, kód aplikace, tajemství, spuštění.
#   REPO_URL=https://github.com/<uživatel>/Domovnik.git DOMOVNIK_HOST=domovnik.local ./bootstrap.sh
set -euo pipefail

REPO_URL="${REPO_URL:?nastav REPO_URL (adresa repozitáře)}"
BRANCH="${BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/domovnik}"
DATA_DIR="${DATA_DIR:-/data}"
DOMOVNIK_HOST="${DOMOVNIK_HOST:-$(hostname -f 2>/dev/null || hostname)}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends ca-certificates curl git gnupg ufw openssl cron

# Docker z oficiálního repozitáře
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
fi

# Firewall: jen SSH a web (přístup zvenčí řeš přes VPN, porty nevystavuj do internetu)
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 8080/tcp
ufw --force enable

mkdir -p "$DATA_DIR/pgdata" "$DATA_DIR/files" "$DATA_DIR/backups"

# Kód aplikace
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" pull --ff-only
fi

# Tajemství (jen poprvé; soubor deploy/.env se nikdy nepřepisuje)
ENV_FILE="$APP_DIR/deploy/.env"
if [ ! -f "$ENV_FILE" ]; then
  cp "$APP_DIR/deploy/.env.prod.example" "$ENV_FILE"
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" "$ENV_FILE"
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$(openssl rand -hex 32)|" "$ENV_FILE"
  sed -i "s|^DOMOVNIK_HOST=.*|DOMOVNIK_HOST=${DOMOVNIK_HOST}|" "$ENV_FILE"
  sed -i "s|^DATA_DIR=.*|DATA_DIR=${DATA_DIR}|" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Vytvořen $ENV_FILE s vygenerovanými tajemstvími."
  echo "ZÁLOHUJ SI HO – SECRET_KEY šifruje API klíče uložené v databázi."
fi

# Denní záloha databáze (viz deploy/backup)
install -m 0755 "$APP_DIR/deploy/backup/backup.sh" /usr/local/bin/domovnik-backup
cat > /etc/cron.d/domovnik-backup <<CRON
30 3 * * * root APP_DIR=$APP_DIR DATA_DIR=$DATA_DIR /usr/local/bin/domovnik-backup >> /var/log/domovnik-backup.log 2>&1
CRON

cd "$APP_DIR"
docker compose -f deploy/compose.prod.yml --env-file deploy/.env up -d --build

echo
echo "Hotovo. Aplikace běží na https://${DOMOVNIK_HOST}/ (první otevření vytvoří administrátora)."
echo "Další informace: docs/06-nasazeni.md"
