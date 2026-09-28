# fototrip

Turns a folder of geotagged photos into a self-contained static website: an
OpenStreetMap map with thumbnail markers that cluster when you zoom out, a
lightbox with next/prev, and a day-by-day time axis that filters the map.

## Install

```bash
python3 -m venv ~/src/venv/fototrip
~/src/venv/fototrip/bin/pip install -e .
```

## Use

```bash
~/src/venv/fototrip/bin/fototrip build "2026-07 Argentina" -o site --title "Argentina 2026"
~/src/venv/fototrip/bin/fototrip serve site
```

`build` flags: `-o/--out` (default `site`), `--title` and `--subtitle`
(override `trip.toml` and the folder name), `--thumb-px` (default 96, the
square marker/cluster thumbnail), `--web-px` (default 1600, the long-edge
cap on the lightbox image), `--no-geocode` and `--places-cache` (see "Place
names" below). `serve` takes `-p/--port` (default 8000).

The output in `site/` is fully static: copy it anywhere that serves files. It
needs no API key and fetches nothing from a CDN at runtime. The one exception
is `.fototrip-cache.json` (see below) — it is build metadata for `fototrip`
itself, not something the site needs, so it does not need to be uploaded
alongside the rest of `site/`.

Optional `trip.toml` in the photo folder, overridden by the CLI flags:

```toml
title = "Argentina 2026"
subtitle = "Iguazu, Buenos Aires"
tile_url = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
tile_attribution = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
```

`tile_url` and `tile_attribution` override the default OpenStreetMap tiles —
for example to point at a different provider. Both default to OpenStreetMap
if omitted.

A build is incremental: it caches derivatives by each source file's path
(relative to the trip folder), size and mtime, plus the `--thumb-px`/
`--web-px` in effect, in `<out>/.fototrip-cache.json`, so re-running after
adding a few photos only processes what changed. `--thumb-px` and `--web-px`
are one shared part of every entry's signature, so changing either one
invalidates every entry and rebuilds both derivatives for every photo, not
just the size that changed — a deliberately simple, if coarser, rule. The
key is relative to the trip folder rather than absolute, so the cache
file — which lives inside the folder the rest of this README tells you to
publish — never carries your home directory or folder layout.

## Place names

The lightbox shows each photo's capture date, its local capture time, and a
readable place — "Cataratas del Iguazú, Puerto Iguazú, Argentinien" rather
than a pair of coordinates.

The names come from OpenStreetMap's Nominatim service, looked up **at build
time only**: the published site still makes no third-party requests and needs
no API key. Nominatim's usage policy allows one request per second, so the
build spaces them out and caches every answer. Coordinates are rounded to
about 110 m for the lookup, which on a real trip collapses ~950 photos into
~130 requests: roughly two minutes the first time, and nothing at all
afterwards.

The cache lives at `~/.cache/fototrip/places.json`, outside the output
folder, so `rm -rf site` does not throw those lookups away. Move it with
`--places-cache PATH`. It stores only the rounded coordinate, never a photo's
exact position.

Geocoding is best-effort and never fatal. Build without a network connection
and you get a site without place names, reported as "without a name" in the
build summary; the next build with a connection fills them in. Turn it off
entirely with `--no-geocode`.

## How days are decided

Photo timestamps are read together with their coordinates: the timezone comes
from the location, not from the camera's EXIF offset. The phones on this trip
stayed on German time, so an evening photo in Argentina carries a `+02:00`
offset and a timestamp after midnight. Grouping on the raw stamp would file it
under the wrong day.

This is not theoretical: building the real 2026-07 Argentina trip (935 photos
included) turned up 90 photos whose resolved local day differs from what a
naive read of the raw EXIF stamp would give, all of them stamped between
00:00 and 05:00 on the camera's German clock and correctly rolled back to the
previous evening in Argentina. For example `IMG_6842.jpeg` carries
`DateTimeOriginal 2026:08:02 00:38:21` with `OffsetTimeOriginal +02:00` at
Buenos Aires coordinates; fototrip resolves that to local time
`2026-08-01T19:38:21-03:00` and files it under `2026-08-01`, not the
`2026-08-02` a naive reading of the stamp would suggest.

## Known limits

- Videos (`.mov`) are ignored.
- Photos without GPS coordinates or without a timestamp are skipped. The build
  reports how many and why.
- The site embeds every photo's exact coordinates, so anyone with the URL has
  the trip's GPS track.

## Development

```bash
~/src/venv/fototrip/bin/pip install -e ".[dev]"
~/src/venv/fototrip/bin/playwright install chromium   # once, for the browser tests
~/src/venv/fototrip/bin/pytest            # everything
~/src/venv/fototrip/bin/pytest -k frontend  # test_frontend*.py: mostly Playwright, plus a couple of manifest-shape checks that launch no browser
~/src/venv/fototrip/bin/ruff format src tests
```

`tools/vendor_assets.py` re-downloads the pinned frontend libraries into
`src/fototrip/assets/vendor/` and refreshes `VENDOR.lock.json`. It is a one-time
step; the vendored files are committed so builds need no network.
