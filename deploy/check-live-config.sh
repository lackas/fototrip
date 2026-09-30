#!/usr/bin/env bash
# Compare what the server actually answers with against Caddyfile.fototrip.lackas.net.
#
#   deploy/check-live-config.sh ~/trips
#
# The Caddy block is not imported from this repo -- it is pasted into the
# server's single global Caddyfile by hand. So the file here is a copy, and on
# 2026-09-30 the two drifted: the repo listed both tile hosts in img-src, the
# server only the wildcard, and a CSP wildcard does not cover the bare host.
# Every map tile was refused by our own policy. The browser test passed the
# whole time, because it checked a string in the test file.
#
# Read-only: HEAD requests, nothing is changed. Run from deploy.sh after rsync.
set -euo pipefail

SOURCE="${1:?usage: check-live-config.sh <folder of built trips>}"
URL="${FOTOTRIP_URL:-https://fototrip.lackas.net}"
CADDYFILE="$(dirname "$0")/Caddyfile.fototrip.lackas.net"

fail=0
note() { printf '    %s\n' "$*"; }
bad() { printf '    MISMATCH: %s\n' "$*" >&2; fail=1; }

# One header value, lowercased name, whitespace-trimmed, from a HEAD request.
header_of() {
	curl -sI "$1" | awk -v want="$2" '
		BEGIN { IGNORECASE = 1 }
		index(tolower($0), want ":") == 1 {
			sub(/^[^:]*:[ \t]*/, ""); sub(/\r$/, ""); print
		}'
}

# A path under SOURCE matching the glob, as a site-relative URL path, or empty.
relative_match() {
	local hit
	hit=$(find "$SOURCE" -type f -path "$2" -print -quit 2>/dev/null || true)
	[ -n "$hit" ] || return 0
	printf '%s' "${hit#"$SOURCE"/}"
}

echo "==> Content-Security-Policy"
want_csp=$(sed -n 's/.*Content-Security-Policy "\([^"]*\)".*/\1/p' "$CADDYFILE")
[ -n "$want_csp" ] || { echo "no policy found in $CADDYFILE" >&2; exit 1; }
live_csp=$(header_of "$URL/" "content-security-policy")
if [ "$live_csp" = "$want_csp" ]; then
	note "matches the repo copy"
else
	bad "Content-Security-Policy"
	printf '      repo: %s\n      live: %s\n' "$want_csp" "${live_csp:-<absent>}" >&2
fi

# The tile URL the generator writes has to be permitted by that policy. This is
# the coupling that broke: a change in site.py silently invalidates the config.
# Checked against the LIVE policy, not the repo copy: the browser enforces
# what the server sends, and that is the distinction this whole script exists
# for.
echo "==> the tile host the build actually uses is allowed by the LIVE policy"
manifest=$(relative_match "$SOURCE" '*/photos.json')
if [ -z "$manifest" ]; then
	note "no photos.json under $SOURCE, skipped"
else
	host=$(python3 -c '
import json, sys, urllib.parse
url = json.load(open(sys.argv[1]))["tiles"]["url"]
print(urllib.parse.urlsplit(url).netloc)' "$SOURCE/$manifest")
	# A CSP host-source with a *. prefix requires at least one label in front
	# of the rest, so it never matches the bare domain. That is the whole bug.
	if python3 -c '
import sys
host, policy = sys.argv[1], sys.argv[2]
sources = next((d.split()[1:] for d in policy.split(";") if d.split()[:1] == ["img-src"]), [])
for s in sources:
    s = s.removeprefix("https://")
    if s == host or (s.startswith("*.") and host.endswith(s[1:]) and host != s[2:]):
        sys.exit(0)
sys.exit(1)' "$host" "${live_csp:-}"; then
		note "$host is covered"
	else
		bad "$host is the tile host in photos.json, but the live img-src does not allow it"
	fi
fi

echo "==> Cache-Control per kind of file"
# glob under SOURCE                     expected Cache-Control
check_cache() {
	local rel="$1" want="$2" label="$3"
	[ -n "$rel" ] || { note "no $label found under $SOURCE, skipped"; return; }
	local got
	got=$(header_of "$URL/$rel" "cache-control")
	if [ "$got" = "$want" ]; then
		note "$label ($rel): $got"
	else
		bad "$label ($rel): expected '$want', got '${got:-<absent>}'"
	fi
}
check_cache "$(relative_match "$SOURCE" '*/vendor/*')" \
	"public, max-age=31536000, immutable" "vendored library"
check_cache "$(relative_match "$SOURCE" '*/photos.json')" "no-cache" "manifest"
check_cache "$(relative_match "$SOURCE" '*/web/*.jpg')" \
	"public, max-age=86400" "photo derivative"
check_cache "index.html" "no-cache" "overview page"

if [ "$fail" -ne 0 ]; then
	echo >&2
	echo "The live Caddyfile does not match deploy/Caddyfile.fototrip.lackas.net." >&2
	echo "Paste the block from that file into /var/www/caddy/conf/Caddyfile, then:" >&2
	echo "  /var/www/caddy/reformat.sh && /var/www/caddy/reload.sh" >&2
	exit 1
fi
echo "==> live config matches the repo"
