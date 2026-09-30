import json
import locale

from fototrip.site import TripConfig, render_site

MANIFEST = {
    "photos": [
        {
            "id": "IMG_1",
            "thumb": "thumb/IMG_1.jpg",
            "web": "web/IMG_1.jpg",
            "w": 480,
            "h": 640,
            "lat": -25.685817,
            "lon": -54.4435,
            "t": "2026-07-19T10:12:12-03:00",
            "day": "2026-07-19",
            "camera": "iPhone 17 Pro",
        }
    ],
    "days": [{"day": "2026-07-19", "count": 1}],
    "bounds": [[-25.685817, -54.4435], [-25.685817, -54.4435]],
}


def test_writes_index_manifest_and_assets(tmp_path):
    render_site(MANIFEST, TripConfig(title="Argentina"), tmp_path)
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "photos.json").exists()
    assert (tmp_path / "app.js").exists()
    assert (tmp_path / "app.css").exists()
    assert (tmp_path / "vendor" / "leaflet" / "leaflet.js").exists()
    assert (tmp_path / "vendor" / "photoswipe" / "photoswipe.esm.js").exists()


def test_manifest_round_trips_as_json(tmp_path):
    render_site(MANIFEST, TripConfig(title="Argentina"), tmp_path)
    written = json.loads((tmp_path / "photos.json").read_text())
    # Every key the manifest went in with, unchanged -- plus the trip's name,
    # which render_site adds on the way out.
    assert {k: written[k] for k in MANIFEST} == MANIFEST
    assert written["title"] == "Argentina"


def test_title_appears_in_the_page(tmp_path):
    render_site(MANIFEST, TripConfig(title="Argentina 2026", subtitle="17 days"), tmp_path)
    html = (tmp_path / "index.html").read_text()
    assert "<title>Argentina 2026</title>" in html
    assert "17 days" in html


def test_all_asset_references_are_relative(tmp_path):
    """The site must work from a subdirectory of any static host."""
    render_site(MANIFEST, TripConfig(title="T"), tmp_path)
    html = (tmp_path / "index.html").read_text()
    assert 'src="/' not in html
    assert 'href="/' not in html
    assert "unpkg.com" not in html
    assert "cdn." not in html


def test_osm_attribution_is_present(tmp_path):
    render_site(MANIFEST, TripConfig(title="T"), tmp_path)
    assert "openstreetmap.org/copyright" in (tmp_path / "index.html").read_text()


def test_title_is_escaped(tmp_path):
    render_site(MANIFEST, TripConfig(title="Trip <script>alert(1)</script>"), tmp_path)
    html = (tmp_path / "index.html").read_text()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_config_defaults_when_no_toml_present(tmp_path):
    config = TripConfig.load(tmp_path)
    assert config.title == tmp_path.name
    assert "openstreetmap" in config.tile_url


def test_config_reads_trip_toml(tmp_path):
    (tmp_path / "trip.toml").write_text('title = "Argentina"\nsubtitle = "Iguazu to BA"\n')
    config = TripConfig.load(tmp_path)
    assert (config.title, config.subtitle) == ("Argentina", "Iguazu to BA")


def test_cli_overrides_beat_trip_toml(tmp_path):
    (tmp_path / "trip.toml").write_text('title = "From file"\n')
    assert TripConfig.load(tmp_path, title="From flag").title == "From flag"


def test_rerender_replaces_stale_manifest(tmp_path):
    render_site(MANIFEST, TripConfig(title="T"), tmp_path)
    render_site({"photos": [], "days": [], "bounds": None}, TripConfig(title="T"), tmp_path)
    assert json.loads((tmp_path / "photos.json").read_text())["photos"] == []


def test_non_ascii_title_written_as_utf8_regardless_of_locale(tmp_path):
    """render_site must write UTF-8 explicitly, so a title with an em dash or an accented
    character survives a build under a non-UTF-8 process locale (e.g. a C/POSIX locale in
    a container or cron job), instead of raising UnicodeEncodeError or writing mojibake."""
    title = "Argentinien-Reise — Iguazú"
    saved_locale = locale.setlocale(locale.LC_ALL, None)
    try:
        locale.setlocale(locale.LC_ALL, "C")
        render_site(MANIFEST, TripConfig(title=title), tmp_path)
    finally:
        locale.setlocale(locale.LC_ALL, saved_locale)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert title in html


def test_rerender_removes_stale_vendor_files(tmp_path):
    """A rebuild must not leave orphaned files from a previous vendor tree behind."""
    render_site(MANIFEST, TripConfig(title="T"), tmp_path)
    orphan = tmp_path / "vendor" / "old-lib" / "old.js"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("stale")

    render_site(MANIFEST, TripConfig(title="T"), tmp_path)

    assert not orphan.exists()
    assert (tmp_path / "vendor" / "leaflet" / "leaflet.js").exists()


def test_the_manifest_carries_the_trip_title(tmp_path):
    """An overview page over several built trips needs their names.

    The title lives in the rendered HTML, which is awkward to read back;
    photos.json is the file every consumer already parses.
    """
    render_site(MANIFEST, TripConfig(title="Iceland", subtitle="ring road"), tmp_path)
    written = json.loads((tmp_path / "photos.json").read_text())
    assert written["title"] == "Iceland"
    assert written["subtitle"] == "ring road"


def test_rendering_does_not_mutate_the_caller_s_manifest(tmp_path):
    """render_site adds to the payload it writes, not to the dict it was given."""
    manifest = {"photos": [], "days": [], "bounds": None}
    render_site(manifest, TripConfig(title="Iceland"), tmp_path)
    assert "title" not in manifest


def test_the_manifest_carries_the_tile_configuration(tmp_path):
    """So the page needs no inline script to hand it to app.js.

    An inline script is the one thing that forces `script-src 'unsafe-inline'`
    into the Content-Security-Policy of whatever serves this.
    """
    render_site(MANIFEST, TripConfig(title="Iceland"), tmp_path)
    written = json.loads((tmp_path / "photos.json").read_text())
    assert written["tiles"]["url"].startswith("https://")
    assert "OpenStreetMap" in written["tiles"]["attribution"]


def test_a_custom_tile_provider_reaches_the_manifest(tmp_path):
    render_site(
        MANIFEST,
        TripConfig(
            title="Iceland",
            tile_url="https://tiles.example/{z}/{x}/{y}.png",
            tile_attribution="Example",
        ),
        tmp_path,
    )
    written = json.loads((tmp_path / "photos.json").read_text())
    assert written["tiles"] == {
        "url": "https://tiles.example/{z}/{x}/{y}.png",
        "attribution": "Example",
    }


def test_the_page_carries_no_inline_script(tmp_path):
    """Every <script> must have a src, so `script-src 'self'` suffices."""
    import re

    render_site(MANIFEST, TripConfig(title="Iceland"), tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")

    for tag, body in re.findall(r"<script([^>]*)>(.*?)</script>", html, re.DOTALL):
        assert "src=" in tag, f"inline script: {body.strip()[:80]}"
        assert body.strip() == "", f"script with both src and body: {body.strip()[:80]}"


def test_the_cover_travels_from_trip_toml_into_the_manifest(tmp_path):
    (tmp_path / "trip.toml").write_text('cover = "IMG_5659"\n')
    out = tmp_path / "site"
    render_site(MANIFEST, TripConfig.load(tmp_path), out)
    assert json.loads((out / "photos.json").read_text())["cover"] == "IMG_5659"


def test_the_page_links_back_to_the_overview(tmp_path):
    """Trips are deployed side by side under the overview, one level up."""
    render_site(MANIFEST, TripConfig(title="T"), tmp_path)
    assert '<a class="back" href="../">' in (tmp_path / "index.html").read_text()
