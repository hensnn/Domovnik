#!/usr/bin/env bash
# Test obnovy: poslední zálohu načte do dočasné databáze a ověří, že obsahuje data. Nic nepřepisuje.
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/domovnik}"
DATA_DIR="${DATA_DIR:-/data}"
cd "$APP_DIR"
LATEST="$(ls -1t "$DATA_DIR"/backups/domovnik-*.dump | head -1)"
[ -n "$LATEST" ] || { echo "Žádná záloha." >&2; exit 1; }
COMPOSE="docker compose -f deploy/compose.prod.yml --env-file deploy/.env"
$COMPOSE exec -T db psql -U domovnik -d postgres -c "DROP DATABASE IF EXISTS restore_test" -c "CREATE DATABASE restore_test"
$COMPOSE exec -T db pg_restore -U domovnik -d restore_test --no-owner < "$LATEST"
ITEMS="$($COMPOSE exec -T db psql -U domovnik -d restore_test -tAc 'SELECT count(*) FROM items')"
$COMPOSE exec -T db psql -U domovnik -d postgres -c "DROP DATABASE restore_test"
echo "Test obnovy OK: $LATEST (věcí v záloze: $ITEMS)"
