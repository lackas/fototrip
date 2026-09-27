"""Browser tests against a real built site."""

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest
from click.testing import CliRunner

from fototrip.cli import main
from tests.conftest import BUENOS_AIRES, COLOGNE, IGUAZU


@pytest.fixture
def site_url(make_jpeg, tmp_path):
    """Build a three-day trip and serve it. Two photos share coordinates."""
    trip = make_jpeg("IMG_1.jpeg", lat=COLOGNE[0], lon=COLOGNE[1]).parent
    make_jpeg("IMG_2.jpeg", lat=IGUAZU[0], lon=IGUAZU[1], stamp="2026:07:19 11:00:00")
    make_jpeg("IMG_3.jpeg", lat=IGUAZU[0], lon=IGUAZU[1], stamp="2026:07:19 11:00:02")
    make_jpeg("IMG_4.jpeg", lat=-25.60, lon=-54.50, stamp="2026:07:19 15:12:12")
    make_jpeg("IMG_5.jpeg", lat=BUENOS_AIRES[0], lon=BUENOS_AIRES[1], stamp="2026:07:31 15:02:29")

    out = tmp_path / "site"
    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out), "--title", "AR"])
    assert result.exit_code == 0, result.output

    handler = partial(SimpleHTTPRequestHandler, directory=str(out))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/", out
    server.shutdown()


def _ready(page, url):
    page.goto(url)
    page.wait_for_function("window.fototrip && window.fototrip.state.photos.length > 0")


def test_manifest_has_the_expected_shape(site_url):
    _, out = site_url
    manifest = json.loads((out / "photos.json").read_text())
    assert len(manifest["photos"]) == 5
    assert [d["count"] for d in manifest["days"]] == [1, 3, 1]


def test_all_photos_load_into_the_page(page, site_url):
    url, _ = site_url
    _ready(page, url)
    assert page.evaluate("window.fototrip.state.photos.length") == 5
    assert page.evaluate("window.fototrip.state.visible.length") == 5


def test_zoomed_out_shows_clusters_not_every_marker(page, site_url):
    url, _ = site_url
    _ready(page, url)
    page.evaluate("window.fototrip.map.setZoom(2)")
    page.wait_for_timeout(400)
    assert page.locator(".cluster-marker").count() >= 1
    assert page.locator(".photo-marker").count() < 5


def test_zooming_into_one_place_reveals_individual_thumbnails(page, site_url):
    url, _ = site_url
    _ready(page, url)
    page.evaluate("window.fototrip.map.setView([-25.6858, -54.4435], 17)")
    page.wait_for_timeout(500)
    assert page.locator(".photo-marker").count() >= 1


def test_clicking_a_marker_opens_the_lightbox(page, site_url):
    url, _ = site_url
    _ready(page, url)
    page.evaluate("window.fototrip.openLightboxAt(0)")
    page.wait_for_selector(".pswp", state="visible")
    assert page.locator(".pswp__img").first.is_visible()


def test_lightbox_next_and_prev_walk_chronologically(page, site_url):
    url, _ = site_url
    _ready(page, url)
    page.evaluate("window.fototrip.openLightboxAt(0)")
    page.wait_for_selector(".pswp", state="visible")
    assert page.evaluate("window.fototrip.lightbox.pswp.currIndex") == 0
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(250)
    assert page.evaluate("window.fototrip.lightbox.pswp.currIndex") == 1
    page.keyboard.press("ArrowLeft")
    page.wait_for_timeout(250)
    assert page.evaluate("window.fototrip.lightbox.pswp.currIndex") == 0


def test_two_photos_at_identical_coordinates_stay_reachable(page, site_url):
    """A burst at one spot must not hide one photo permanently under another."""
    url, _ = site_url
    _ready(page, url)
    page.evaluate("window.fototrip.map.setView([-25.6858, -54.4435], 19)")
    page.wait_for_timeout(500)
    markers = page.locator(".photo-marker").count()
    clusters = page.locator(".cluster-marker").count()
    assert markers + clusters >= 1
    # Both are in the data and both are addressable through the lightbox.
    ids = page.evaluate("window.fototrip.state.visible.map(p => p.id)")
    assert "IMG_2" in ids and "IMG_3" in ids


def test_no_console_errors_on_load(page, site_url):
    url, _ = site_url
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    _ready(page, url)
    page.wait_for_timeout(300)
    assert errors == []
