#!/usr/bin/env bash
# Přístup přes VPN bez domény: nastaví adresu pro interní HTTPS (Caddy), vyexportuje jeho kořenový
# certifikát a ověří, že s ním HTTPS funguje. Spouští se UVNITŘ LXC jako root.
#   ./vpn-https.sh                      # adresa = první IP kontejneru
#   ./vpn-https.sh 192.168.0.15         # IP nebo jméno, které telefon použije v prohlížeči
#   ./vpn-https.sh 192.168.0.15 --serve # navíc na 5 minut zpřístupní certifikát ke stažení z telefonu
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/domovnik}"
ENV_FILE="$APP_DIR/deploy/.env"
OUT_DIR="${OUT_DIR:-$APP_DIR/certs}"
OUT="$OUT_DIR/domovnik-root.crt"
SERVE_PORT="${SERVE_PORT:-8099}"
SERVE_SECONDS="${SERVE_SECONDS:-300}"

HOST=""
SERVE=0
for arg in "$@"; do
  case "$arg" in
    --serve) SERVE=1 ;;
    -h | --help)
      sed -n 2,7p "$0"
      exit 0
      ;;
    *) HOST="$arg" ;;
  esac
done
HOST="${HOST:-$(hostname -I | awk '{print $1}')}"
[ -n "$HOST" ] || { echo "Nepodařilo se zjistit IP kontejneru – zadej ji jako parametr." >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "Chybí $ENV_FILE – nejdřív spusť bootstrap.sh." >&2; exit 1; }

# Nastaví KLÍČ=hodnota v deploy/.env (přepíše, nebo přidá). Ostatní řádky nechá být.
set_env() {
  if grep -q "^$1=" "$ENV_FILE"; then
    sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"
  fi
}

compose() {
  docker compose -f "$APP_DIR/deploy/compose.prod.yml" --env-file "$ENV_FILE" "$@"
}

echo ">> Adresa aplikace: https://$HOST/"
set_env DOMOVNIK_HOST "$HOST"
set_env CADDYFILE /etc/caddy/Caddyfile
set_env HTTP_PORT 80
set_env HTTPS_PORT 443

echo ">> Restartuji web (Caddy) a vystavuji certifikát…"
cd "$APP_DIR"
compose up -d --force-recreate web

mkdir -p "$OUT_DIR"
for _ in $(seq 1 30); do
  if compose cp web:/data/caddy/pki/authorities/local/root.crt "$OUT" 2>/dev/null && [ -s "$OUT" ]; then
    break
  fi
  sleep 1
done
[ -s "$OUT" ] || { echo "Kořenový certifikát se nepodařilo získat (compose logs web)." >&2; exit 1; }
chmod 644 "$OUT"

echo ">> Ověřuji HTTPS s tímto certifikátem…"
ok=0
for _ in $(seq 1 15); do
  if curl -fsS --max-time 5 --cacert "$OUT" "https://$HOST/api/v1/auth/status" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 2
done
if [ "$ok" = 1 ]; then
  echo "   OK – HTTPS na $HOST funguje a je podepsané tímto certifikátem."
else
  echo "   POZOR: ověření selhalo. Zkontroluj 'docker compose … logs web'." >&2
fi

FP="$(openssl x509 -in "$OUT" -noout -fingerprint -sha256 | cut -d= -f2)"
cat <<EOF

Kořenový certifikát: $OUT
SHA-256 otisk:       $FP

Instalace na zařízení (jednorázově, VPN musí být zapnutá):
  Android  Nastavení → Zabezpečení → Šifrování a přihlašovací údaje → Instalovat certifikát → CA certifikát
  iPhone   otevři soubor, Nastavení → Profil stažen → Instalovat; pak Nastavení → Obecné → Informace →
           Nastavení důvěry certifikátů → zapnout plnou důvěru
  Windows  (PowerShell jako správce)  certutil -addstore -f Root domovnik-root.crt
  Linux    sudo cp domovnik-root.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates
Pak otevři https://$HOST/ (Firefox na Androidu má vlastní úložiště certifikátů).
EOF

if [ "$SERVE" = 1 ]; then
  command -v python3 >/dev/null || { echo "Pro --serve je potřeba python3 (apt-get install -y python3)." >&2; exit 1; }
  TMP="$(mktemp -d)"
  cp "$OUT" "$TMP/domovnik-root.crt"
  ufw allow "$SERVE_PORT/tcp" >/dev/null
  cleanup() {
    ufw delete allow "$SERVE_PORT/tcp" >/dev/null 2>&1 || true
    rm -rf "$TMP"
  }
  trap cleanup EXIT
  echo
  echo ">> Stažení z telefonu (přes VPN), platí $((SERVE_SECONDS / 60)) min:"
  echo "   http://$HOST:$SERVE_PORT/domovnik-root.crt"
  echo "   Před důvěrou porovnej otisk výše (iPhone ho ukáže v detailu profilu)."
  timeout "$SERVE_SECONDS" python3 - "$TMP" "$SERVE_PORT" <<'PY' || true
import functools
import http.server
import sys

directory, port = sys.argv[1], int(sys.argv[2])


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".crt": "application/x-x509-ca-cert",
    }


http.server.ThreadingHTTPServer(
    ("0.0.0.0", port), functools.partial(Handler, directory=directory)
).serve_forever()
PY
  echo ">> Stahování ukončeno, port $SERVE_PORT je zavřený."
fi
