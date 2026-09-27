import json

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
    assert json.loads((tmp_path / "photos.json").read_text()) == MANIFEST


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
