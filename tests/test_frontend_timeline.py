"""Browser tests for the day strip."""


def _ready(page, url):
    page.goto(url)
    page.wait_for_function("window.fototrip && window.fototrip.state.photos.length > 0")


def test_one_cell_per_day_plus_all(page, site_url):
    url, _ = site_url
    _ready(page, url)
    assert page.locator("#timeline .day-cell").count() == 4  # All + 3 days
    assert page.locator("#timeline .day-cell.all").count() == 1


def test_all_days_is_selected_on_load(page, site_url):
    url, _ = site_url
    _ready(page, url)
    selected = page.locator('.day-cell[aria-pressed="true"]')
    assert selected.count() == 1
    assert "all" in selected.get_attribute("class")
    assert page.evaluate("window.fototrip.state.selectedDay") is None
    assert page.evaluate("window.fototrip.state.visible.length") == 6


def test_selecting_a_day_filters_the_visible_set(page, site_url):
    url, _ = site_url
    _ready(page, url)
    page.click('.day-cell[data-day="2026-07-19"]')
    page.wait_for_timeout(300)
    assert page.evaluate("window.fototrip.state.visible.length") == 4
    assert page.evaluate("window.fototrip.state.visible.every(p => p.day === '2026-07-19')")


def test_selecting_a_day_refits_the_map(page, site_url):
    url, _ = site_url
    _ready(page, url)
    page.evaluate("window.fototrip.selectDay('2026-07-17')")  # Cologne
    page.wait_for_timeout(400)
    cologne = page.evaluate("window.fototrip.map.getCenter().lat")
    page.evaluate("window.fototrip.selectDay('2026-07-31')")  # Buenos Aires
    page.wait_for_timeout(400)
    buenos_aires = page.evaluate("window.fototrip.map.getCenter().lat")
    assert cologne > 40
    assert buenos_aires < -30


def test_a_single_photo_day_does_not_slam_the_map_to_max_zoom(page, site_url):
    """2026-07-31 holds exactly one photo, so fitBounds would get a zero-area
    box without paddedBounds. Zoom alone can't prove this: fitTo's own
    maxZoom: 16 already caps the zoom at 16 for both a padded and an
    unpadded box here (measured — see task-11-report.md), so a bare
    '8 <= zoom <= 16' assertion would still pass with paddedBounds deleted
    outright. What actually differs is the bounds object paddedBounds hands
    to fitBounds, so record that argument directly by wrapping
    map.fitBounds before triggering the selection, and assert it is not
    zero-area."""
    url, _ = site_url
    _ready(page, url)
    page.evaluate(
        """() => {
          const map = window.fototrip.map;
          const original = map.fitBounds.bind(map);
          window.__lastFitBounds = null;
          map.fitBounds = (bounds, opts) => {
            window.__lastFitBounds = {
              latSpan: bounds.getNorth() - bounds.getSouth(),
              lonSpan: bounds.getEast() - bounds.getWest(),
            };
            return original(bounds, opts);
          };
        }"""
    )
    page.evaluate("window.fototrip.selectDay('2026-07-31')")
    page.wait_for_timeout(400)
    span = page.evaluate("window.__lastFitBounds")
    assert span["latSpan"] > 0 and span["lonSpan"] > 0, (
        f"paddedBounds handed fitBounds a zero-area box: {span}"
    )
    # The zoom cap still applies either way — kept as a sanity check, not the
    # discriminating assertion.
    zoom = page.evaluate("window.fototrip.map.getZoom()")
    assert 8 <= zoom <= 16, f"zoom was {zoom}"


def test_returning_to_all_days_restores_every_photo(page, site_url):
    url, _ = site_url
    _ready(page, url)
    page.click('.day-cell[data-day="2026-07-19"]')
    page.wait_for_timeout(200)
    page.click(".day-cell.all")
    page.wait_for_timeout(300)
    assert page.evaluate("window.fototrip.state.visible.length") == 6


def test_lightbox_only_walks_the_selected_day(page, site_url):
    url, _ = site_url
    _ready(page, url)
    page.evaluate("window.fototrip.selectDay('2026-07-19')")
    page.wait_for_timeout(200)
    page.evaluate("window.fototrip.openLightboxAt(0)")
    page.wait_for_selector(".pswp", state="visible")
    assert page.evaluate("window.fototrip.lightbox.pswp.getNumItems()") == 4


def test_arrow_keys_step_between_days(page, site_url):
    url, _ = site_url
    _ready(page, url)
    page.evaluate("window.fototrip.selectDay('2026-07-17')")
    page.wait_for_timeout(200)
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(300)
    assert page.evaluate("window.fototrip.state.selectedDay") == "2026-07-19"
    page.keyboard.press("ArrowLeft")
    page.wait_for_timeout(300)
    assert page.evaluate("window.fototrip.state.selectedDay") == "2026-07-17"


def test_bar_heights_are_proportional_to_the_day_count(page, site_url):
    url, _ = site_url
    _ready(page, url)
    busy = page.locator('.day-cell[data-day="2026-07-19"] .bar').bounding_box()["height"]
    quiet = page.locator('.day-cell[data-day="2026-07-31"] .bar').bounding_box()["height"]
    assert busy > quiet


def test_day_cells_fit_inside_the_timeline_without_clipping(page, site_url):
    """#timeline clips overflow-y, so a cell taller than its content box loses
    pixels off the top silently — bounding_box() alone can't catch that, since
    it reports the un-clipped layout box, not what survives the ancestor's
    overflow clip. Compare each cell's rendered height against the strip's
    actual content box instead."""
    url, _ = site_url
    _ready(page, url)
    measured = page.evaluate(
        """() => {
          const timeline = document.getElementById('timeline');
          const cs = getComputedStyle(timeline);
          const contentHeight =
            timeline.clientHeight -
            parseFloat(cs.paddingTop) -
            parseFloat(cs.paddingBottom);
          const heights = [...document.querySelectorAll('#timeline .day-cell')].map(
            (cell) => cell.getBoundingClientRect().height
          );
          return { contentHeight, heights };
        }"""
    )
    overflowing = [h for h in measured["heights"] if h > measured["contentHeight"]]
    assert overflowing == [], (
        f"cell(s) {overflowing} taller than the timeline's content box "
        f"({measured['contentHeight']}px) — they will be clipped by "
        f"#timeline's overflow-y: hidden"
    )
