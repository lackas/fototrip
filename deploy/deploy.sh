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
ROOT="${FOTOTRIP_ROOT:-/home/fototrip}"
URL="${FOTOTRIP_URL:-https://fototrip.lackas.net}"

[ -f "$SOURCE/index.html" ] || {
	echo "$SOURCE has no index.html -- run 'fototrip index $SOURCE' first" >&2
	exit 1
}

echo "==> $SOURCE -> $HOST:$ROOT/"
# No -z: JPEGs do not compress and it only burns CPU at both ends.
# --delete so photos dropped by a rebuild do not stay online.
# .fototrip-cache.json is build metadata; the site does not need it.
rsync -a --delete --partial \
	--exclude '.fototrip-cache.json' --exclude 'trips.toml' \
	"$SOURCE/" "$HOST:$ROOT/"

# The password check has to come from an address that is not exempt from it.
# The Caddy block lets the house address and the tailnet in without a prompt
# (`Satisfy Any`, effectively), so probing from the laptop answers 200 and an
# earlier version of this script read that as "published without a password"
# and aborted a perfectly good deploy. The server's own public address is not
# on that list, so it sees what a stranger sees.
#
# No credentials anywhere, so this script carries no secret. A 401 proves Caddy
# is serving this host and is actually asking -- which is the failure worth
# catching, since a missing basic_auth block would answer 200 and put the trips
# on the open internet.
echo "==> smoke test (probed from $HOST, which basic_auth applies to)"
code=$(ssh "$HOST" "curl -s -o /dev/null -w '%{http_code}' $URL/")
echo "$URL/ -> HTTP $code"
case "$code" in
	401) echo "    serving, and asking for the password" ;;
	200) echo "    WARNING: answered without asking for a password" >&2; exit 1 ;;
	*)   echo "    unexpected status" >&2; exit 1 ;;
esac

# The Caddy block lives in the server's global Caddyfile and is maintained by
# hand, so the copy in this directory can drift from it. It did, and a CSP that
# no longer covered the tile host blocked every map tile while the test suite
# stayed green. Never again silently.
"$(dirname "$0")/check-live-config.sh" "$SOURCE"
