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

The output in `site/` is fully static: copy it anywhere that serves files. It
needs no API key and fetches nothing from a CDN at runtime.

Optional `trip.toml` in the photo folder, overridden by the CLI flags:

```toml
title = "Argentina 2026"
subtitle = "Iguazu, Buenos Aires"
```

A build is incremental: it caches derivatives by each source file's size and
mtime in `<out>/.fototrip-cache.json`, so re-running after adding a few photos
only processes what changed.

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
~/src/venv/fototrip/bin/pytest            # everything
~/src/venv/fototrip/bin/pytest -k frontend  # browser tests, needs: playwright install chromium
~/src/venv/fototrip/bin/ruff format src tests
```

`tools/vendor_assets.py` re-downloads the pinned frontend libraries into
`src/fototrip/assets/vendor/` and refreshes `VENDOR.lock.json`. It is a one-time
step; the vendored files are committed so builds need no network.
