#!/usr/bin/env bash
# Push a folder of built trips to server.lackas.net.
#
#   fototrip index ~/trips --title "Unsere Reisen"
#   deploy/deploy.sh ~/trips
#
# The overview is built locally and travels with the trips, so the server needs
# nothing installed -- Caddy serves the directory and that is all. See
# DEPLOY.md for the one-off setup.
set -euo pipefail

SOURCE="${1:?usage: deploy.sh <folder of built trips>}"
HOST="${FOTOTRIP_HOST:-lackas@server.lackas.net}"
ROOT="${FOTOTRIP_ROOT:-/home/lackas/Data/Fototrips}"
URL="${FOTOTRIP_URL:-https://fototrip.lackas.net}"

[ -f "$SOURCE/index.html" ] || {
	echo "$SOURCE has no index.html -- run 'fototrip index $SOURCE' first" >&2
	exit 1
}

echo "==> $SOURCE -> $HOST:$ROOT/"
# No -z: JPEGs do not compress and it only burns CPU at both ends.
# --delete so photos dropped by a rebuild do not stay online.
# .fototrip-cache.json is build metadata; the site does not need it.
rsync -a --delete --partial --info=progress2 \
	--exclude '.fototrip-cache.json' \
	"$SOURCE/" "$HOST:$ROOT/"

# Without credentials, so the script carries no secret. A 401 proves Caddy is
# serving this host and that the password is actually being asked for -- which
# is the failure worth catching, since a missing basic_auth block would answer
# 200 and put the trips on the open internet.
echo "==> smoke test"
code=$(curl -s -o /dev/null -w '%{http_code}' "$URL/")
echo "$URL/ -> HTTP $code"
case "$code" in
	401) echo "    serving, and asking for the password" ;;
	200) echo "    WARNING: answered without asking for a password" >&2; exit 1 ;;
	*)   echo "    unexpected status" >&2; exit 1 ;;
esac
