# Serving trips from server.lackas.net

The built sites are static and reference everything relatively, so several of
them side by side under one web root need no configuration and no process.
Caddy's `file_server` is the whole runtime; `fototrip serve` is a development
convenience and plays no part here.

```
/home/lackas/Data/Fototrips/      ->  /srv/fototrips  (read-only in the container)
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
mkdir -p /home/lackas/Data/Fototrips
```

**2. Mount it into the Caddy container**, read-only, following the same
pattern as `ting` and `emit-cache`. In `/var/www/caddy/docker-compose.yml`
(root-owned), under the `caddy` service's volumes:

```yaml
- /home/lackas/Data/Fototrips:/srv/fototrips:ro
```

Then `docker compose up -d` in `/var/www/caddy`. This recreates the container,
so every host it serves is briefly down. A symlink out of `sites/` is not an
alternative: the target would be outside the mount and unresolvable inside the
container.

**3. The password.**

```bash
docker exec -it caddy caddy hash-password --bcrypt-cost 12
```

`--bcrypt-cost 12` on purpose. The other hosts use the default 14, which is
around a second of CPU per verification; a gallery page issues a hundred-plus
image requests, each carrying the credentials. Caddy caches verified ones, but
14 leaves no headroom if that cache misses, and 12 is ample for a private
photo host.

**4. The Caddy block.** Paste `Caddyfile.fototrip.lackas.net` from this
directory into `/var/www/caddy/conf/Caddyfile`, with the hash from step 3 in
place of `REPLACE_WITH_BCRYPT_HASH`, then:

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

The smoke test at the end expects **401**. A 200 would mean the site is
answering without asking for the password, which is the failure actually worth
catching.

## If a trip should be public

Drop the `basic_auth` block for that host. Bear in mind what the README says:
the site embeds every photo's exact coordinates, so anyone with the URL has the
trip's GPS track.
