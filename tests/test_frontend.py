"""Browser tests against a real built site."""

import json
import re
from pathlib import Path


def _ready(page, url):
    page.goto(url)
    page.wait_for_function("window.fototrip && window.fototrip.state.photos.length > 0")


def test_manifest_has_the_expected_shape(site_url):
    _, out = site_url
    manifest = json.loads((out / "photos.json").read_text())
    assert len(manifest["photos"]) == 6
    assert [d["count"] for d in manifest["days"]] == [1, 4, 1]


def test_the_after_midnight_iguazu_photo_files_under_the_earlier_local_day(site_url):
    """Pins the project's core property end to end: IMG_6 carries the naive
    stamp 2026-07-20T01:30:00+02:00 at Iguazu coordinates. A naive read of
    the raw stamp would file it under 2026-07-20; resolved from its
    coordinates it is 2026-07-19T20:30:00-03:00, one local day earlier --
    exactly the after-midnight case the README's "How days are decided"
    section describes."""
    _, out = site_url
    manifest = json.loads((out / "photos.json").read_text())
    entry = next(p for p in manifest["photos"] if p["id"] == "IMG_6")
    assert entry["t"] == "2026-07-19T20:30:00-03:00"
    assert entry["day"] == "2026-07-19"


def test_all_photos_load_into_the_page(page, site_url):
    url, _ = site_url
    _ready(page, url)
    assert page.evaluate("window.fototrip.state.photos.length") == 6
    assert page.evaluate("window.fototrip.state.visible.length") == 6


def test_thumbnail_images_actually_load(page, site_url):
    """No existing assertion proves a marker's background image ever
    actually loaded -- a broken `thumb` URL (e.g. an unsanitised filename
    ending the CSS string or 404ing on a stray '#') would still pass every
    other test here, since none of them inspect the image itself. Load the
    URL for real and check it decoded to a non-empty image."""
    url, _ = site_url
    _ready(page, url)
    page.evaluate("window.fototrip.map.setView([-25.60, -54.50], 17)")
    page.wait_for_timeout(500)
    thumb_url = page.evaluate(
        """() => {
          const el = document.querySelector('.photo-marker');
          const bg = getComputedStyle(el).backgroundImage;
          const match = /url\\((['"]?)(.*?)\\1\\)/.exec(bg);
          return match ? match[2] : null;
        }"""
    )
    assert thumb_url, "no .photo-marker with a background-image was found"
    natural_width = page.evaluate(
        """(src) => new Promise((resolve) => {
          const img = new Image();
          img.onload = () => resolve(img.naturalWidth);
          img.onerror = () => resolve(0);
          img.src = src;
        })""",
        thumb_url,
    )
    assert natural_width > 0, f"thumbnail at {thumb_url!r} did not load"


def test_zoomed_out_shows_clusters_not_every_marker(page, site_url):
    url, _ = site_url
    _ready(page, url)
    page.evaluate("window.fototrip.map.setZoom(2)")
    page.wait_for_timeout(400)
    assert page.locator(".cluster-marker").count() >= 1
    assert page.locator(".photo-marker").count() < 6


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


def _open_lightbox_on(page, photo_id):
    index = page.evaluate(
        "id => window.fototrip.state.visible.findIndex(p => p.id === id)", photo_id
    )
    assert index >= 0, f"{photo_id} is not in the visible set"
    page.evaluate("i => window.fototrip.openLightboxAt(i)", index)
    page.wait_for_selector(".pswp__custom-caption", state="visible")


def test_the_lightbox_caption_shows_the_photos_own_local_time(page, site_url):
    """IMG_6 is stamped 2026-07-20 01:30 +02:00 at Iguazu, i.e. 20:30 on the 19th
    local. The browser sits in Europe/Berlin, where that instant is 01:30 on the
    20th -- so a caption built with the viewer's timezone would read wrong."""
    url, _ = site_url
    _ready(page, url)
    _open_lightbox_on(page, "IMG_6")

    when = page.locator(".pswp__custom-caption .caption-when").inner_text()
    assert "19. Juli 2026" in when
    assert "20:30" in when
    assert "01:30" not in when


def test_the_lightbox_caption_shows_the_place(page, site_url):
    url, _ = site_url
    _ready(page, url)
    _open_lightbox_on(page, "IMG_2")

    where = page.locator(".pswp__custom-caption .caption-where").inner_text()
    assert where == "Cataratas del Iguazú, Puerto Iguazú, Argentinien"


def test_the_caption_names_the_weekday_and_month_in_german(page, site_url):
    url, _ = site_url
    _ready(page, url)
    _open_lightbox_on(page, "IMG_1")

    when = page.locator(".pswp__custom-caption .caption-when").inner_text()
    assert when.startswith("Fr., 17. Juli 2026")
    assert "19:37" in when


def test_the_caption_follows_next_and_prev(page, site_url):
    url, _ = site_url
    _ready(page, url)
    _open_lightbox_on(page, "IMG_1")
    first = page.locator(".pswp__custom-caption .caption-when").inner_text()

    # Advance through PhotoSwipe's own API rather than the keyboard: the arrow
    # keys are covered by test_lightbox_next_and_prev_walk_chronologically, and
    # what this test is about is that the caption follows the slide.
    page.evaluate("window.fototrip.lightbox.pswp.next()")
    page.wait_for_timeout(300)
    second = page.locator(".pswp__custom-caption .caption-when").inner_text()

    assert second != first


def test_a_photo_without_a_place_shows_only_the_time(page, site_url):
    url, _ = site_url
    _ready(page, url)
    page.evaluate("window.fototrip.state.visible[0].place = null")
    page.evaluate("window.fototrip.openLightboxAt(0)")
    page.wait_for_selector(".pswp__custom-caption", state="visible")

    assert page.locator(".pswp__custom-caption .caption-when").inner_text() != ""
    assert page.locator(".pswp__custom-caption .caption-where").count() == 0


def _map_centre(page):
    return page.evaluate(
        "() => { const c = window.fototrip.map.getCenter(); return [c.lat, c.lng]; }"
    )


def _is_clustered(page, photo_id):
    """True when this photo's marker is currently hidden inside a cluster."""
    return page.evaluate(
        """(id) => {
          const marker = window.fototrip.markers.get(id);
          return !!marker && window.fototrip.clusterGroup.getVisibleParent(marker) !== marker;
        }""",
        photo_id,
    )


def _open_lightbox(page, index):
    """Open at `index` and wait until it is really open, not merely visible.

    PhotoSwipe's opener refuses to close while it is still opening -- read
    `close()` in vendor/photoswipe/photoswipe.esm.js: it returns silently when
    `isOpening`, because "browsers aren't good at changing the direction of
    the CSS transition". A test that closes too early gets a no-op and then
    waits forever for a teardown that never starts. So wait on that exact
    flag rather than on a timeout that happens to be long enough.
    """
    page.evaluate("(i) => window.fototrip.openLightboxAt(i)", index)
    page.wait_for_selector(".pswp", state="visible")
    page.wait_for_function(
        "() => { const p = window.fototrip.lightbox.pswp; return !!p && p.opener.isOpen; }"
    )


def _close_lightbox(page):
    page.evaluate("() => window.fototrip.lightbox.pswp.close()")
    page.wait_for_function("() => !window.fototrip.lightbox.pswp")


def test_closing_the_lightbox_lands_on_the_photo_you_were_looking_at(page, site_url):
    """Walk away from the photo you opened, then close: the map follows.

    Zoomed out over a trip spanning two continents the photo's marker is
    inside a cluster, so centring alone would land you on a cluster badge and
    tell you nothing. The zoom is raised to the same cap fitTo already uses.
    """
    url, _ = site_url
    _ready(page, url)
    assert page.evaluate("window.fototrip.map.getZoom()") < 10

    _open_lightbox(page, 0)
    page.evaluate("() => { const p = window.fototrip.lightbox.pswp; p.next(); p.next(); }")
    page.wait_for_function("window.fototrip.lightbox.pswp.currIndex === 2")

    photo = page.evaluate("() => window.fototrip.state.visible[2]")
    assert _is_clustered(page, photo["id"]), "precondition: photo 2 should be in a cluster here"

    _close_lightbox(page)
    page.wait_for_function(
        """(p) => {
          const c = window.fototrip.map.getCenter();
          return Math.abs(c.lat - p.lat) < 1e-4 && Math.abs(c.lng - p.lon) < 1e-4;
        }""",
        arg=photo,
    )
    assert page.evaluate("window.fototrip.map.getZoom()") == 16


def test_closing_the_lightbox_leaves_the_zoom_alone_when_the_photo_stands_alone(page, site_url):
    """The zoom you were working in survives, which is the whole point.

    This is the half that can break silently: raising the zoom unconditionally
    would still pass the test above, and you would only notice by being thrown
    out of your own view on every single photo you close.
    """
    url, _ = site_url
    _ready(page, url)

    index = page.evaluate("() => window.fototrip.state.visible.findIndex((p) => p.lat < -30)")
    assert index >= 0, "the fixture trip should hold one Buenos Aires photo"
    photo = page.evaluate("(i) => window.fototrip.state.visible[i]", index)

    # Deliberately NOT centred on the photo: about a kilometre off, so that
    # "the map stayed put" and "the map moved to the photo and kept the zoom"
    # are distinguishable. Centred exactly, this test would pass with the
    # feature removed entirely.
    page.evaluate(
        "(p) => window.fototrip.map.setView([p.lat + 0.01, p.lon + 0.01], 15, { animate: false })",
        photo,
    )
    assert not _is_clustered(page, photo["id"]), "precondition: it stands alone at this zoom"

    _open_lightbox(page, index)
    _close_lightbox(page)

    assert page.evaluate("window.fototrip.map.getZoom()") == 15
    centre = _map_centre(page)
    assert abs(centre[0] - photo["lat"]) < 1e-4 and abs(centre[1] - photo["lon"]) < 1e-4


def test_the_map_gets_its_tiles_from_the_manifest(page, site_url):
    """The tile layer is added after photos.json arrives, not from an inline
    script in the page. If that wiring breaks, the map is simply blank."""
    url, _ = site_url
    _ready(page, url)

    layers = page.evaluate(
        """() => {
          let tiles = 0;
          window.fototrip.map.eachLayer((l) => { if (l instanceof L.TileLayer) tiles++; });
          return tiles;
        }"""
    )
    assert layers == 1

    # and the tiles are actually being requested
    page.wait_for_function("() => document.querySelectorAll('img.leaflet-tile').length > 0")


CADDYFILE = Path(__file__).parent.parent / "deploy" / "Caddyfile.fototrip.lackas.net"


def _deployed_csp() -> str:
    """The policy out of the Caddy config, not a copy of it kept here.

    A copy is what let this break in production: the test asserted a string in
    this file, the server answered a different one, and the difference -- a
    wildcard that does not cover the bare host -- blocked every tile. The
    policy has exactly one home in this repo, and it is the file that gets
    pasted into the server.
    """
    match = re.search(r'Content-Security-Policy "([^"]+)"', CADDYFILE.read_text())
    assert match, f"no Content-Security-Policy found in {CADDYFILE}"
    return match.group(1)


STRICT_CSP = _deployed_csp()


def test_the_page_works_under_the_content_security_policy_it_is_served_with(page, site_url):
    """The deployed policy, enforced, against the real page.

    Every other browser test here runs with no policy at all, so none of them
    would notice an inline script or an inline style creeping back in -- the
    site would keep passing its tests and break the moment it was served.

    Two things below look redundant and are not. The policy is read back off
    the document response, because the first version of this test built its
    route pattern from a URL that already ended in a slash, matched nothing,
    and spent its whole life checking a page that was served no policy at all.
    And the tiles are checked for naturalWidth rather than for existing: a
    blocked image still leaves its <img> in the DOM, so counting elements
    cannot tell a loaded tile from a refused one.
    """
    url, _ = site_url
    violations = []
    policies = []
    page.on(
        "console",
        lambda m: (
            violations.append(m.text) if "content security policy" in m.text.lower() else None
        ),
    )
    page.on(
        "response",
        lambda r: (
            policies.append(r.headers.get("content-security-policy"))
            if r.request.resource_type == "document"
            else None
        ),
    )

    def with_csp(route):
        response = route.fetch()
        headers = {**response.headers, "content-security-policy": STRICT_CSP}
        route.fulfill(response=response, headers=headers)

    # Same-origin only: a catch-all here would take precedence over the tile
    # stub in conftest and send the requests to OpenStreetMap for real. The
    # rstrip matters -- site_url ends in a slash, and "{url}/**" produces a
    # doubled slash that matches no request at all.
    page.route(url.rstrip("/") + "/**", with_csp)
    _ready(page, url)

    assert policies == [STRICT_CSP], f"the page was not served the policy under test: {policies}"

    # The tiles arrived. Not "an <img> exists" -- a tile the policy refused
    # leaves one of those behind too -- but "the browser has pixels for it",
    # which is what the wildcard-only policy took away in production.
    page.wait_for_function(
        """() => {
             const tiles = [...document.querySelectorAll('img.leaflet-tile')];
             return tiles.length > 0 && tiles.every((t) => t.complete && t.naturalWidth > 0);
           }"""
    )
    # and the lightbox still opens, which is where PhotoSwipe styles the DOM
    page.evaluate("() => window.fototrip.openLightboxAt(0)")
    page.wait_for_selector(".pswp", state="visible")
    assert page.locator(".pswp__img").first.is_visible()

    assert violations == [], violations

    # Routes left in flight outlive this test and break the setup of whichever
    # test the fixture hands the next page to -- which looked like an unrelated
    # failure in another file.
    page.unroute_all(behavior="ignoreErrors")


def _deployed_referrer_policy() -> str:
    match = re.search(r'Referrer-Policy "([^"]+)"', CADDYFILE.read_text())
    assert match, f"no Referrer-Policy found in {CADDYFILE}"
    return match.group(1)


def test_tile_requests_carry_a_referer_under_the_deployed_referrer_policy(page, site_url):
    """OpenStreetMap's tile policy requires a Referer from browser apps, and
    without one real Chrome gets the yellow-and-black "Access blocked" tile.

    The site serves `Referrer-Policy: no-referrer` on purpose, so photo URLs do
    not leak anywhere; the tile layer has to override that for its own images.
    Headless Chromium was let through without a Referer, which is why the live
    check came back green while the browser that mattered saw 403s.
    """
    url, _ = site_url
    referers = []

    def with_policy(route):
        response = route.fetch()
        headers = {**response.headers, "referrer-policy": _deployed_referrer_policy()}
        route.fulfill(response=response, headers=headers)

    page.on(
        "request",
        lambda r: (
            referers.append(r.all_headers().get("referer", ""))
            if "tile.openstreetmap.org" in r.url
            else None
        ),
    )
    page.route(url.rstrip("/") + "/**", with_policy)
    _ready(page, url)
    page.wait_for_function("() => document.querySelectorAll('img.leaflet-tile').length > 0")

    origin = url.split("/", 3)[:3]
    assert referers, "no tile was requested"
    # Only the origin -- the page path names the trip and has no business
    # travelling to a third party.
    assert set(referers) == {"/".join(origin) + "/"}, referers

    page.unroute_all(behavior="ignoreErrors")
