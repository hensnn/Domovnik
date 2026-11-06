#!/usr/bin/env bash
# Denní záloha databáze (pg_dump) do $DATA_DIR/backups s rotací. Fotky leží v /data/files
# a zálohuje je vzdump LXC (PBS) – tady je jen konzistentní dump databáze.
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/domovnik}"
DATA_DIR="${DATA_DIR:-/data}"
KEEP_DAYS="${KEEP_DAYS:-14}"
OUT="$DATA_DIR/backups"
mkdir -p "$OUT"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="$OUT/domovnik-$STAMP.dump"
COMPOSE="docker compose -f deploy/compose.prod.yml --env-file deploy/.env"

cd "$APP_DIR"
$COMPOSE exec -T db pg_dump -U domovnik -d domovnik --format=custom --no-owner > "$FILE.tmp"
mv "$FILE.tmp" "$FILE"
# kontrola, že dump jde přečíst
$COMPOSE exec -T db pg_restore --list < "$FILE" > /dev/null
find "$OUT" -name 'domovnik-*.dump' -mtime +"$KEEP_DAYS" -delete
echo "$(date -Is) záloha OK: $FILE ($(du -h "$FILE" | cut -f1))"
