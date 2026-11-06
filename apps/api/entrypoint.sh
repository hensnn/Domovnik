#!/bin/sh
# Spuštění API: nejdřív migrace databáze (idempotentní), pak aplikace.
set -e
if [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
  echo "Spouštím migrace databáze…"
  domovnik migrate
fi
exec "$@"
