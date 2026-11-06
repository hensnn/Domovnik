#!/usr/bin/env bash
# Obnova databáze ze zálohy:  ./restore.sh /data/backups/domovnik-YYYYMMDD-HHMMSS.dump
# POZOR: přepíše aktuální databázi. Fotky se obnovují z PBS (vzdump) nebo ze zálohy /data/files.
set -euo pipefail
FILE="${1:?uveď soubor se zálohou}"
APP_DIR="${APP_DIR:-/opt/domovnik}"
cd "$APP_DIR"
read -r -p "Přepsat databázi zálohou $FILE? (ano/ne) " answer
[ "$answer" = "ano" ] || { echo "Zrušeno."; exit 1; }
COMPOSE="docker compose -f deploy/compose.prod.yml --env-file deploy/.env"
$COMPOSE stop api
$COMPOSE exec -T db psql -U domovnik -d postgres -c "DROP DATABASE IF EXISTS domovnik WITH (FORCE)" -c "CREATE DATABASE domovnik"
$COMPOSE exec -T db pg_restore -U domovnik -d domovnik --no-owner < "$FILE"
$COMPOSE start api
echo "Obnova dokončena."
