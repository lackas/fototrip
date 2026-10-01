"""Turn coordinates into a human-readable place label, via OpenStreetMap.

Standalone by design: only stdlib imports, so this module can be reasoned
about (and tested) without pulling in the rest of the package. The one HTTP
call is injected, so no test ever needs the network.

Geocoding happens at BUILD time, never in the browser: the published site
stays free of API keys and third-party requests. Results are cached on a
coarse grid outside the output folder, so the ~2 minutes of lookups a new
trip costs are paid once and never again, even after `rm -rf site`.
"""

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# ~110 m. A burst of photos at one spot, or a walk around one building, should
# be a single lookup: Nominatim's answer would be the same anyway, and a finer
# grid only multiplies requests against a service that asks for one per second.
_GRID_DECIMALS = 3

# A label names one place and then situates it: "Cataratas del Iguazú, Puerto
# Iguazú, Argentinien". So the keys are grouped by SCALE rather than kept in
# one flat specificity order, and at most one name is taken from each group.
#
# Flat ordering looked right and was not: real Nominatim data for Cologne
# carries both `suburb` and `neighbourhood`, which produced "Altstadt-Nord,
# Martinsviertel, Deutschland" -- two adjacent districts and no city.
#
# `road` is absent on purpose: a street name is precise but tells a reader far
# less than the district it is in. `country` is absent because it is appended
# last, so every label ends with it.
_LOCAL_KEYS = (
    "tourism",
    "attraction",
    "leisure",
    "natural",
    "historic",
    "building",
    "suburb",
    "neighbourhood",
    "quarter",
    "city_district",
)
_SETTLEMENT_KEYS = (
    "village",
    "town",
    "city",
    "municipality",
    "county",
    "state",
)

# OSM names carry stray runs of whitespace, e.g. "Bº  El Pilar" as returned.
_WHITESPACE = re.compile(r"\s+")


def _readable(name: str) -> bool:
    """True when every letter is Latin, accented or not.

    Nominatim falls back to the local name when it has neither a German nor an
    English one, which put "Συνοικία Κολωνακίου" and "ตำบลเกาะเต่า" into the
    captions. By code point rather than by Unicode name, because "º" in
    "Bº El Pilar" is a letter whose name does not say LATIN. Everything up to
    Latin Extended-B, plus Latin Extended Additional for Vietnamese.
    """
    return all(not ch.isalpha() or ord(ch) < 0x250 or 0x1E00 <= ord(ch) <= 0x1EFF for ch in name)


NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

# Nominatim's usage policy requires an identifying User-Agent and at most one
# request per second. Both are honoured here; see Geocoder.
USER_AGENT = "fototrip/0.1 (static trip-photo site generator; github.com/lackas)"
MIN_INTERVAL_SECONDS = 1.0


def label_from_address(address: dict) -> str | None:
    """Build a short label from a Nominatim `address` dict.

    Takes at most one name per scale -- a local feature or district, then the
    settlement or region containing it -- and appends the country, so every
    label ends with it. On a trip spanning two continents the country is the
    part that orients a reader fastest.

    Repeats are skipped: Nominatim frequently returns the same string under
    several keys, for instance a city that is also its own province.
    """
    parts: list[str] = []
    for keys in (_LOCAL_KEYS, _SETTLEMENT_KEYS, ("country",)):
        for key in keys:
            value = address.get(key)
            if not isinstance(value, str):
                continue
            value = _WHITESPACE.sub(" ", value).strip()
            if value and value not in parts and _readable(value):
                parts.append(value)
                break

    return ", ".join(parts) or None


def _grid_key(lat: float, lon: float) -> str:
    return f"{round(lat, _GRID_DECIMALS)},{round(lon, _GRID_DECIMALS)}"


class PlaceCache:
    """Labels already looked up, keyed on a coarse coordinate grid.

    Stores a successful label as a string and a coordinate Nominatim had no
    usable name for as JSON null, so the second kind is remembered rather than
    asked about on every build. A *failed request* is deliberately not stored,
    so an offline build does not poison the cache.

    Only the rounded coordinate is written, never the photo's exact position:
    this file is a build artifact, and the precise track already lives in
    photos.json where it is meant to.
    """

    #: Returned by `get` for a coordinate that has never been looked up, so
    #: that a cached "no name here" (None) stays distinguishable from it.
    MISS = object()

    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: dict[str, str | None] = {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(loaded, dict):
            # A label in another script was cached before label_from_address
            # learnt to skip such names, and would otherwise stay that way for
            # good. Dropping it makes it a miss, so the next build asks again.
            self._entries = {
                k: v
                for k, v in loaded.items()
                if v is None or (isinstance(v, str) and _readable(v))
            }

    def get(self, lat: float, lon: float):
        """Return the cached label, None for a known-unnamed place, or MISS."""
        return self._entries.get(_grid_key(lat, lon), self.MISS)

    def put(self, lat: float, lon: float, label: str | None) -> None:
        self._entries[_grid_key(lat, lon)] = label

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._entries, ensure_ascii=False, indent=0, sort_keys=True),
            encoding="utf-8",
        )


@dataclass
class GeocodeStats:
    cached: int = 0
    looked_up: int = 0
    unnamed: int = 0
    failed: int = 0


def fetch_address(lat: float, lon: float) -> dict:
    """Ask Nominatim what is at these coordinates. Returns its `address` dict."""
    query = urllib.parse.urlencode(
        {
            "lat": f"{lat:.6f}",
            "lon": f"{lon:.6f}",
            "format": "jsonv2",
            "zoom": "17",
            "addressdetails": "1",
            # English fills the gaps German leaves: Κολωνάκι comes back as
            # Kolonaki. Whatever is local-only after that, label_from_address
            # skips.
            "accept-language": "de,en",
        }
    )
    request = urllib.request.Request(f"{NOMINATIM_URL}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    address = payload.get("address")
    return address if isinstance(address, dict) else {}


class Geocoder:
    """Coordinates to labels, cached, rate-limited, and never fatal.

    A lookup failure is counted and yields no label. A build without network
    therefore produces a site without place names rather than no site at all.
    """

    def __init__(
        self,
        cache: PlaceCache,
        *,
        fetch=fetch_address,
        min_interval: float = MIN_INTERVAL_SECONDS,
        sleep=time.sleep,
        clock=time.monotonic,
    ) -> None:
        self.cache = cache
        self.stats = GeocodeStats()
        self._fetch = fetch
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    def label_for(self, lat: float, lon: float) -> str | None:
        cached = self.cache.get(lat, lon)
        if cached is not PlaceCache.MISS:
            self.stats.cached += 1
            return cached

        self._wait_for_slot()
        try:
            address = self._fetch(lat, lon)
        except Exception:  # noqa: BLE001 -- deliberately broad, see comment below
            # Offline, a timeout, a 5xx, a malformed payload, a DNS failure: all
            # of them mean the same thing here, and enumerating them would only
            # invite the one that was not on the list to abort a whole build.
            # Not cached, so a later run tries again.
            self.stats.failed += 1
            return None

        label = label_from_address(address) if isinstance(address, dict) else None
        self.cache.put(lat, lon, label)
        self.stats.looked_up += 1
        if label is None:
            self.stats.unnamed += 1
        return label

    def _wait_for_slot(self) -> None:
        """Hold requests to at most one per `min_interval`, per OSM's policy."""
        now = self._clock()
        if self._last_request is not None:
            elapsed = now - self._last_request
            if elapsed < self._min_interval:
                self._sleep(self._min_interval - elapsed)
        self._last_request = self._clock()
