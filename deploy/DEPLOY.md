# Serving trips from server.lackas.net

The built sites are static and reference everything relatively, so several of
them side by side under one web root need no configuration and no process.
Caddy's `file_server` is the whole runtime; `fototrip serve` is a development
convenience and plays no part here.

```
/home/fototrip/                   ->  /srv/fototrip   (read-only in the container)
    index.html                        the overview, built by `fototrip index`
    argentina-2026/                   a built site, copied as it is
    norway-2025/
```

## One-off setup

Three of these need Christian: two need root, and one is a password.

**1. The directory for the photos.** Not under `/var/www/caddy/sites/`: that is
on the `/var` volume, which has about 66 GB free and also carries Docker and
the logs. A trip is roughly 850 MB. `/home` has 2.9 TB.

```bash
mkdir -p /home/fototrip
```

**2. Mount it into the Caddy container**, read-only, following the same
pattern as `ting` and `emit-cache`. In `/var/www/caddy/docker-compose.yml`
(root-owned), under the `caddy` service's volumes:

```yaml
- /home/fototrip:/srv/fototrip:ro
```

Then `docker compose up -d` in `/var/www/caddy`. This recreates the container,
so every host it serves is briefly down. A symlink out of `sites/` is not an
alternative: the target would be outside the mount and unresolvable inside the
container.

`/var/www/caddy/sites/` is itself mounted as `/srv`, so the directory
`sites/fototrip` **is** the mountpoint `/srv/fototrip`. It must stay, even
though it looks like an empty leftover: removing it drops the nested mount out
of the container's namespace and every URL answers 404 while the files sit
untouched on the host. `docker restart caddy` puts it back.

**3. The password.** The user is `fototrip`, not a personal login -- this
guards one host, and the credentials get handed to whoever should see the
photos.

```bash
docker exec -it caddy caddy hash-password --bcrypt-cost 4
```

Cost 4 on purpose, against the 14 the other hosts use. This is a screen against
search engines and idle URL-guessing, not protection from someone who has the
server -- whoever can read the hash can read the JPEGs beside it. Measured on
this machine: cost 4 is 1.0 ms per verification, 11 is 105 ms, 14 is 830 ms,
and one gallery page issues over a hundred image requests that each carry the
credentials.

The trade is real, though: a cost-4 hash falls to an offline attack in minutes.
**Use a password you use nowhere else.**

**4. The Caddy block.** Paste `Caddyfile.fototrip.lackas.net` from this
directory into `/var/www/caddy/conf/Caddyfile` and replace its four
placeholders, which the comment at its top explains: the hash from step 3 for
`BCRYPT_HASH_SIEHE_SERVER`, the house address for `HOME_IP`, and two separate
`openssl rand -hex 32` values for `UNLOCK_PATH_SIEHE_SERVER` and
`COOKIE_WERT_SIEHE_SERVER`. The real values exist only on the server; this
repository is public. Then:

```bash
/var/www/caddy/reformat.sh && /var/www/caddy/reload.sh
```

No DNS entry and no `tls` directive: `*.lackas.net` resolves via wildcard DNS
and Caddy obtains the certificate on the first request.

`/var/www/caddy` is a git repo without a remote whose `conf/Caddyfile` carries
uncommitted live changes. Never run `git checkout` or `git reset` in there.

## Every deploy after that

```bash
fototrip build "2026-07 Argentina" -o ~/trips/argentina-2026 --title "Argentina 2026"
fototrip index ~/trips --title "Unsere Reisen"
deploy/deploy.sh ~/trips
```

`rsync` only sends what changed, so a rebuilt trip costs its differences rather
than its 850 MB. The overview is built locally and travels with the trips, so
nothing needs installing on the server.

A new trip needs no Caddy and no compose change: a new subdirectory under
`/home/fototrip/` and another `fototrip index` run is the whole of it. The host
is generic.

The smoke test at the end expects **401**, and it is run over ssh from the
server rather than from here. The Caddy block lets the house address and the
tailnet in without a password, so a probe from the laptop answers 200 -- which
an earlier version of the script read as "published without a password" and
aborted on. The server's own address is not on that list, so it sees what a
stranger sees.

## Keeping the live config and this directory in agreement

`Caddyfile.fototrip.lackas.net` is **a copy**. The live block is pasted by hand
into the server's global Caddyfile, which means the two can drift, and on
2026-09-30 they did: this directory listed both tile hosts in `img-src`, the
server listed only the wildcard, and the map went blank for every visitor while
the test suite stayed green.

`deploy/check-live-config.sh` now closes that gap, and `deploy.sh` runs it after
every rsync. It is read-only -- HEAD requests only -- and compares what the
server actually answers with against this directory: the policy itself, whether
the tile host in the built `photos.json` is permitted by the **live** policy,
and the `Cache-Control` for each kind of file. Run it on its own any time:

```bash
deploy/check-live-config.sh ~/trips
```

When it reports a mismatch, the live file is what has to change.

## The Content-Security-Policy

Strict, with no `'unsafe-inline'`. That is a property of the pages, not a
lucky accident: the tile configuration travels in `photos.json` rather than in
an inline script, and the overview has its own `overview.css` rather than an
inline `<style>`. `tests/test_frontend.py` loads a real built page with this
exact policy enforced -- read out of `Caddyfile.fototrip.lackas.net`, not
copied into the test -- and fails if an inline block returns or if a tile is
refused.

One consequence of that design: the tile URL is now data rather than code, so
`img-src` and `trip.toml` have to agree. Point `tile_url` at a provider other
than OpenStreetMap and the policy blocks it -- and the failure shows up here,
as a blank map, rather than at build time. Widen `img-src` in the same change.

**A wildcard does not cover the bare domain.** `https://*.tile.openstreetmap.org`
matches `a.tile.openstreetmap.org` and *not* `tile.openstreetmap.org`: a `*.`
host-source requires at least one label in front of the rest. Dropping the
deprecated `{s}` subdomains from the tile URL therefore moved every tile to a
host the policy did not list. Both forms are listed for that reason.

## Caching

Four mutually exclusive rules, deliberately so: none of them depends on the
order Caddy applies same-name directives in, because Leaflet's
`marker-icon.png` would otherwise match both the vendor rule and the image
rule.

| What | Cache-Control | Why |
|------|---------------|-----|
| `*/vendor/*` | `max-age=31536000, immutable` | Version in the path; never changes under it. |
| photos and videos | `max-age=86400` | The filename survives a rebuild but the content need not, so a week would serve a corrected photo wrong for a week. A day lets a rebuild heal itself while same-day revisits stay free. |
| `*.json`, `*.js`, `*.css` | `no-cache` | Rewritten by every build. With an ETag revalidation costs a 304, not half a megabyte of `photos.json`. |
| HTML and directory indexes | `no-cache` | A deploy should be visible at once. |

`no-cache` means "revalidate", not "do not store" -- the browser keeps the file
and asks whether it is still current.

Caching the derivatives for a year would need a content hash in their
filenames. Worth doing if the gallery ever gets big enough for the revalidation
round-trips to show.

## If a trip should be public

Drop the `basic_auth` block for that host. Bear in mind what the README says:
the site embeds every photo's exact coordinates, so anyone with the URL has the
trip's GPS track.
