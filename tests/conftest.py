"""Synthetic JPEGs with chosen GPS and timestamps, so no real photos are committed."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import ExifTags, Image
from PIL.TiffImagePlugin import IFDRational

from fototrip.cli import main

COLOGNE = (50.9375, 6.9603)
IGUAZU = (-25.6858, -54.4435)
BUENOS_AIRES = (-34.6037, -58.3816)


def _dms(value: float) -> tuple[IFDRational, IFDRational, IFDRational]:
    value = abs(value)
    degrees = int(value)
    minutes = int((value - degrees) * 60)
    seconds = (value - degrees - minutes / 60) * 3600
    return IFDRational(degrees), IFDRational(minutes), IFDRational(round(seconds, 4))


@pytest.fixture
def make_jpeg(tmp_path):
    def _make(
        name="IMG_0001.jpeg",
        *,
        lat=COLOGNE[0],
        lon=COLOGNE[1],
        stamp="2026:07:17 19:37:59",
        offset="+02:00",
        size=(40, 60),
        camera="iPhone 14 Pro",
        orientation=1,
        subdir=None,
    ) -> Path:
        exif = Image.Exif()
        if camera is not None:
            exif[0x010F] = "Apple"
            exif[0x0110] = camera
        exif[0x0112] = orientation
        sub = {}
        if stamp is not None:
            sub[0x9003] = stamp
        if offset is not None:
            sub[0x9011] = offset
        exif[ExifTags.IFD.Exif] = sub
        if lat is not None and lon is not None:
            exif[ExifTags.IFD.GPSInfo] = {
                1: "S" if lat < 0 else "N",
                2: _dms(lat),
                3: "W" if lon < 0 else "E",
                4: _dms(lon),
            }
        target = tmp_path / subdir / name if subdir else tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, "red").save(target, exif=exif)
        return target

    return _make


@pytest.fixture
def site_url(make_jpeg, tmp_path):
    """Build a three-day trip and serve it. Two photos share coordinates."""
    trip = make_jpeg("IMG_1.jpeg", lat=COLOGNE[0], lon=COLOGNE[1]).parent
    make_jpeg("IMG_2.jpeg", lat=IGUAZU[0], lon=IGUAZU[1], stamp="2026:07:19 11:00:00")
    make_jpeg("IMG_3.jpeg", lat=IGUAZU[0], lon=IGUAZU[1], stamp="2026:07:19 11:00:02")
    make_jpeg("IMG_4.jpeg", lat=-25.60, lon=-54.50, stamp="2026:07:19 15:12:12")
    make_jpeg("IMG_5.jpeg", lat=BUENOS_AIRES[0], lon=BUENOS_AIRES[1], stamp="2026:07:31 15:02:29")
    # Mirrors the real IMG_6842 case: a naive stamp just after midnight on the
    # camera's German clock, at Iguazu coordinates, resolves to local evening
    # of the *previous* day. Pins the project's core property (day-from-
    # coordinates, not day-from-raw-stamp) through the full CLI build rather
    # than only inside localtime.py's own unit tests. Same day bucket as
    # IMG_2/IMG_3/IMG_4 (2026-07-19), so it does not add a fourth day.
    make_jpeg(
        "IMG_6.jpeg", lat=IGUAZU[0], lon=IGUAZU[1], stamp="2026:07:20 01:30:00", offset="+02:00"
    )

    out = tmp_path / "site"
    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out), "--title", "AR"])
    assert result.exit_code == 0, result.output

    handler = partial(SimpleHTTPRequestHandler, directory=str(out))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/", out
    server.shutdown()


# --- geocoding safety net ------------------------------------------------
#
# Reverse geocoding runs during a build. No test may reach the network or
# touch the developer's real ~/.cache/fototrip/places.json, so this fixture
# is autouse: it points the default cache at tmp_path and replaces the one
# HTTP call with a deterministic stub. A test that wants different behaviour
# monkeypatches `fototrip.cli.fetch_address` itself.

STUB_ADDRESSES = {
    COLOGNE: {"suburb": "Altstadt-Nord", "city": "Köln", "country": "Deutschland"},
    IGUAZU: {
        "tourism": "Cataratas del Iguazú",
        "town": "Puerto Iguazú",
        "country": "Argentinien",
    },
    BUENOS_AIRES: {"city": "Buenos Aires", "country": "Argentinien"},
}


def stub_fetch_address(lat, lon):
    """Answer like Nominatim would, for the coordinates the fixtures use."""
    for (known_lat, known_lon), address in STUB_ADDRESSES.items():
        if abs(lat - known_lat) < 0.1 and abs(lon - known_lon) < 0.1:
            return dict(address)
    return {"county": "Irgendwo", "country": "Argentinien"}


@pytest.fixture(autouse=True)
def offline_geocoding(monkeypatch, tmp_path):
    monkeypatch.setattr("fototrip.cli.fetch_address", stub_fetch_address)
    monkeypatch.setattr("fototrip.cli.DEFAULT_PLACES_CACHE", tmp_path / "places.json")


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Pin the browser's timezone.

    The lightbox caption must show each photo's LOCAL capture time, not the
    viewer's. Pinning this to Berlin makes that testable: an Argentina photo
    taken at 20:30 local is 01:30 the next day here, so a caption rendered in
    the browser's zone would read visibly wrong.
    """
    return {**browser_context_args, "timezone_id": "Europe/Berlin", "locale": "de-DE"}
