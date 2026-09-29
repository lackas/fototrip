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
~/src/venv/fototrip/bin/fototrip build trip -o site --title "My Trip"
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
title = "My Trip"
subtitle = "where it went"
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

## Filling the folder from Photos.app

`export-album` fills a trip folder straight from a Photos.app album, so a
build no longer depends on someone having hand-exported the right photos:

```bash
~/src/venv/fototrip/bin/pip install -e ".[album]"   # once; macOS only
~/src/venv/fototrip/bin/fototrip export-album "My Album" \
    -o trip --expect 2500 --replace
```

Photos are converted to JPEG and carry their capture time and — where the
library knows it — their GPS coordinates, written into each file with
`exiftool`. That last part matters for iCloud Shared Albums: Apple strips GPS
from the file it hands out, but the library keeps the location, so exporting
this way recovers coordinates a hand-export loses.

The library is only ever read. One album photo becomes exactly one file:
videos, live-photo motion files, the frames of a burst other than the keeper,
the RAW half of a RAW+JPEG pair and the unedited original of an edited photo
are all skipped, so nothing shows up twice on the map.

`--replace` is required to write into a folder that is not empty, and the
export is staged in `<folder>.incoming/` first: an export that fails, produces
nothing, or writes fewer files than its own run report claimed leaves your
existing folder exactly as it was, and says where the partial export is. The
swap at the end is two renames rather than one atomic step, so a process killed
between them leaves your photos in `<folder>.previous/` — nothing is ever
deleted before the new folder is in place, and the next run refuses to start
until you have looked at that folder and moved or removed it.

`--expect N`, with the album's photo count, sharpens the free-space check and
puts the album's size in the report, which then says how many photos the run
never accounted for. Without it the export still refuses to start below an
absolute free-space floor, and still refuses to replace anything when it
produced no photos, or fewer than its own run report claimed — those checks do
not depend on `--expect`.

Needs `exiftool` (`brew install exiftool`).

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
from the location, not from the camera's EXIF offset. A phone that stays on
its home clock while you travel west stamps an evening photo with the home
offset and a time after midnight. Grouping on the raw stamp would file it under
the wrong day.

This is not theoretical. On the real trip this was built for -- a European
phone kept on `+02:00` through a few weeks four to five hours behind -- 90 of
around 900 photos resolved to a different local day than a naive read of the
raw stamp gives, every one of them stamped between 00:00 and 05:00 on the
camera's home clock and correctly rolled back to the previous evening. A photo
carrying `DateTimeOriginal 2026:08:02 00:38:21` with `OffsetTimeOriginal
+02:00`, taken at a longitude where local time is `-03:00`, resolves to
`2026-08-01T19:38:21-03:00` and is filed under `2026-08-01`, not the
`2026-08-02` a naive reading would suggest.

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

## Duplicates

Re-adding pictures to a shared album creates fresh assets, so an export can
hand out the same frame twice under different names. The build drops the extra
copies and says so:

```
2 skipped:
      2  the same photo twice
```

Two photos count as the same only when their resolved local capture time,
their coordinates and their image content all agree — the content compared
only for photos that already match on time and place, so a burst of different
shots at one instant is kept. The larger file is the one published, since a
shared-album copy is usually the smaller re-encode.

The comparison is on the resolved local time, not the raw EXIF stamp, and that
matters: a real shared album handed out two copies of one frame written
`12:00:34 +00:00` and `09:00:34 -03:00` — the same instant in two notations.
Compared on the raw stamp they look like two different photos.
