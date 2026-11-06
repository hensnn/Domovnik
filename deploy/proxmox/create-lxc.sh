#!/usr/bin/env bash
# Vytvoří LXC kontejner pro Domovník na Proxmoxu. Spouští se NA PROXMOX HOSTU jako root.
#
#   CTID=200 STORAGE=ssdpool DATA_SIZE=100 ./create-lxc.sh
#
# Proměnné (všechny volitelné):
#   CTID              číslo kontejneru (200)
#   HOSTNAME_CT       název (domovnik)
#   STORAGE           úložiště pro rootfs a /data – LVM-thin (ssdpool)
#   TEMPLATE_STORAGE  kde leží šablony (local)
#   ROOTFS_SIZE       velikost systémového disku v GB (32)
#   DATA_SIZE         velikost disku /data v GB (100; databáze + fotky, lze později zvětšit)
#   CORES, MEMORY (MB), SWAP (MB)   (4 / 8192 / 1024)
#   BRIDGE            síťový most (vmbr0); IP: dhcp, nebo IP=192.168.1.50/24 GW=192.168.1.1
set -euo pipefail

CTID="${CTID:-200}"
HOSTNAME_CT="${HOSTNAME_CT:-domovnik}"
STORAGE="${STORAGE:-ssdpool}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
ROOTFS_SIZE="${ROOTFS_SIZE:-32}"
DATA_SIZE="${DATA_SIZE:-100}"
CORES="${CORES:-4}"
MEMORY="${MEMORY:-8192}"
SWAP="${SWAP:-1024}"
BRIDGE="${BRIDGE:-vmbr0}"
IP="${IP:-dhcp}"
GW="${GW:-}"

if pct status "$CTID" >/dev/null 2>&1; then
  echo "Kontejner $CTID už existuje – končím." >&2
  exit 1
fi

# Šablona Debian 12 (stáhne se, pokud chybí)
pveam update >/dev/null
TEMPLATE="$(pveam available --section system | awk '/debian-12-standard/ {print $2}' | sort -V | tail -1)"
if ! pveam list "$TEMPLATE_STORAGE" | grep -q "$TEMPLATE"; then
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
fi

NET="name=eth0,bridge=${BRIDGE},ip=${IP},firewall=1"
[ -n "$GW" ] && NET="${NET},gw=${GW}"

pct create "$CTID" "${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}" \
  --hostname "$HOSTNAME_CT" \
  --unprivileged 1 \
  --features nesting=1,keyctl=1 \
  --cores "$CORES" --memory "$MEMORY" --swap "$SWAP" \
  --rootfs "${STORAGE}:${ROOTFS_SIZE}" \
  --mp0 "${STORAGE}:${DATA_SIZE},mp=/data,backup=1" \
  --net0 "$NET" \
  --onboot 1 \
  --description "Domovník – domácí inventář (Docker Compose)"

pct start "$CTID"
echo "Čekám na síť…"
for _ in $(seq 1 30); do
  pct exec "$CTID" -- ping -c1 -W1 deb.debian.org >/dev/null 2>&1 && break
  sleep 2
done

# Předání bootstrap skriptu dovnitř
HERE="$(cd "$(dirname "$0")" && pwd)"
pct push "$CTID" "$HERE/bootstrap.sh" /root/bootstrap.sh --perms 0755
echo
echo "Kontejner $CTID je připraven. Další krok (nainstaluje Docker a spustí aplikaci):"
echo "  pct exec $CTID -- env REPO_URL=https://github.com/<uživatel>/Domovnik.git /root/bootstrap.sh"
