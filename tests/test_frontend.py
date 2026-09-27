"""Browser tests against a real built site."""

import json


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
    # IMG_4's coordinates, not the IGUAZU pair: two markers at the exact same
    # point can only be split apart by a click-triggered spiderfy, never by
    # zooming alone, so asserting on them here would demand behaviour the
    # clustering library does not provide. IMG_4 sits ~11 km away, alone.
    page.evaluate("window.fototrip.map.setView([-25.60, -54.50], 17)")
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
    # PhotoSwipe's Keyboard module binds its document-level keydown listener
    # from inside the 'bindEvents' event (fired once, after the opening
    # animation) rather than at construction time. Pressing a key before that
    # fires is a silent no-op. So hook 'bindEvents' itself, right as the
    # lightbox is opened, and wait for it before sending the first key —
    # that is the exact event whose handler calls
    # pswp.events.add(document, 'keydown', ...), not just a plausible proxy
    # for it (confirmed by reading vendor/photoswipe/photoswipe.esm.js: the
    # Keyboard class registers on 'bindEvents' in its constructor and its
    # callback adds the document keydown listener synchronously).
    page.evaluate(
        """() => {
          window.__pswpBound = false;
          window.fototrip.openLightboxAt(0);
          const attach = () => {
            const pswp = window.fototrip.lightbox.pswp;
            if (pswp) {
              pswp.on('bindEvents', () => { window.__pswpBound = true; });
            } else {
              requestAnimationFrame(attach);
            }
          };
          attach();
        }"""
    )
    page.wait_for_selector(".pswp", state="visible")
    page.wait_for_function("window.__pswpBound === true")
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
