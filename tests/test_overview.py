"""The overview page that sits in front of several built trips."""

import json

from fototrip.overview import Trip, find_trips, render_overview


def _build_trip(root, name, *, title=None, days, photos=1, thumb="thumb/IMG_1.jpg"):
    """A directory shaped like a built site, with only the parts an overview reads."""
    folder = root / name
    folder.mkdir(parents=True)
    manifest = {
        "photos": [{"id": f"IMG_{i}", "thumb": thumb} for i in range(photos)],
        "days": [{"day": d, "count": 1} for d in days],
        "bounds": None,
    }
    if title is not None:
        manifest["title"] = title
    (folder / "photos.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "index.html").write_text("<html></html>", encoding="utf-8")
    return folder


def test_finds_every_built_trip_under_the_folder(tmp_path):
    _build_trip(tmp_path, "iceland", title="Iceland", days=["2024-05-01"])
    _build_trip(tmp_path, "norway", title="Norway", days=["2025-08-02"])

    trips = find_trips(tmp_path)

    assert [t.title for t in trips] == ["Norway", "Iceland"]


def test_the_newest_trip_comes_first(tmp_path):
    _build_trip(tmp_path, "old", title="Old", days=["2019-01-01", "2019-01-02"])
    _build_trip(tmp_path, "new", title="New", days=["2026-07-17", "2026-08-09"])
    _build_trip(tmp_path, "middle", title="Middle", days=["2022-03-03"])

    assert [t.title for t in find_trips(tmp_path)] == ["New", "Middle", "Old"]


def test_a_trip_carries_its_dates_count_and_cover(tmp_path):
    _build_trip(
        tmp_path,
        "iceland",
        title="Iceland",
        days=["2024-05-01", "2024-05-09"],
        photos=137,
        thumb="thumb/IMG_9.jpg",
    )

    [trip] = find_trips(tmp_path)

    assert (trip.first_day, trip.last_day) == ("2024-05-01", "2024-05-09")
    assert (trip.photos, trip.days) == (137, 2)
    # relative to the overview page, which sits one level above the trip
    # every photo in this fixture shares one thumb, so which index is picked is
    # not what this test is about; test_the_cover_comes_from_the_middle_of_the_trip is
    assert trip.cover == "iceland/thumb/IMG_9.jpg"
    assert trip.href == "iceland/"


def test_a_site_built_before_titles_existed_falls_back_to_its_folder_name(tmp_path):
    """photos.json gained `title` later; older builds must still be listed."""
    _build_trip(tmp_path, "2019-05-iceland", title=None, days=["2019-05-01"])

    [trip] = find_trips(tmp_path)

    assert trip.title == "2019-05-iceland"


def test_directories_that_are_not_built_sites_are_ignored(tmp_path):
    _build_trip(tmp_path, "iceland", title="Iceland", days=["2024-05-01"])
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "todo.txt").write_text("not a site", encoding="utf-8")

    assert [t.title for t in find_trips(tmp_path)] == ["Iceland"]


def test_an_unreadable_manifest_is_skipped_rather_than_fatal(tmp_path):
    """One broken trip must not cost you the overview of all the others."""
    _build_trip(tmp_path, "good", title="Good", days=["2024-05-01"])
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "photos.json").write_text("{not json", encoding="utf-8")

    assert [t.title for t in find_trips(tmp_path)] == ["Good"]


def test_a_trip_with_no_photos_is_skipped(tmp_path):
    _build_trip(tmp_path, "empty", title="Empty", days=[], photos=0)
    _build_trip(tmp_path, "real", title="Real", days=["2024-05-01"])

    assert [t.title for t in find_trips(tmp_path)] == ["Real"]


def test_the_page_lists_every_trip_and_links_to_it(tmp_path):
    trips = [
        Trip(
            title="Iceland",
            href="iceland/",
            cover="iceland/thumb/a.jpg",
            first_day="2024-05-01",
            last_day="2024-05-09",
            photos=137,
            days=2,
            subtitle="",
        ),
        Trip(
            title="Norway",
            href="norway/",
            cover="norway/thumb/b.jpg",
            first_day="2025-08-02",
            last_day="2025-08-02",
            photos=9,
            days=1,
            subtitle="fjords",
        ),
    ]

    render_overview(trips, tmp_path, title="Our trips")

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<title>Our trips</title>" in html
    assert 'href="iceland/"' in html and 'href="norway/"' in html
    assert "iceland/thumb/a.jpg" in html
    assert "137" in html and "fjords" in html


def test_a_title_with_markup_cannot_break_out_of_the_page(tmp_path):
    """Trip titles come from trip.toml or a folder name, so treat them as input."""
    trips = [
        Trip(
            title="<script>alert(1)</script>",
            href="x/",
            cover="x/thumb/a.jpg",
            first_day="2024-05-01",
            last_day="2024-05-01",
            photos=1,
            days=1,
            subtitle="",
        ),
    ]

    render_overview(trips, tmp_path, title="Our trips")

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_an_empty_folder_still_produces_a_page(tmp_path):
    render_overview([], tmp_path, title="Our trips")
    assert "<title>Our trips</title>" in (tmp_path / "index.html").read_text(encoding="utf-8")


def test_a_folder_name_with_a_quote_cannot_break_the_cover_style(tmp_path):
    """The folder name is prepended to the cover path and lands in a CSS url().

    The same shape of bug bit the map markers once: a quote in a filename ended
    the CSS string and escaped the attribute. Directory names are user input.
    """
    _build_trip(tmp_path, "it's a trip", title="Quoted", days=["2024-05-01"])

    [trip] = find_trips(tmp_path)
    render_overview([trip], tmp_path, title="Our trips")

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    # the raw quote must not survive inside the style attribute
    assert "url('it's" not in html
    assert "&#39;" in html or "&#x27;" in html


def test_the_index_command_writes_the_page(tmp_path):
    from click.testing import CliRunner

    from fototrip.cli import main

    _build_trip(tmp_path, "iceland", title="Iceland", days=["2024-05-01"])
    _build_trip(tmp_path, "norway", title="Norway", days=["2025-08-02"])

    result = CliRunner().invoke(main, ["index", str(tmp_path), "--title", "Our trips"])

    assert result.exit_code == 0, result.output
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<title>Our trips</title>" in html
    assert 'href="iceland/"' in html
    assert "2 trips" in result.output


def test_the_index_command_defaults_its_title_to_the_folder_name(tmp_path):
    from click.testing import CliRunner

    from fototrip.cli import main

    folder = tmp_path / "our-trips"
    _build_trip(folder, "iceland", title="Iceland", days=["2024-05-01"])

    result = CliRunner().invoke(main, ["index", str(folder)])

    assert result.exit_code == 0, result.output
    assert "<title>our-trips</title>" in (folder / "index.html").read_text(encoding="utf-8")


def test_the_index_command_says_so_when_it_found_nothing(tmp_path):
    from click.testing import CliRunner

    from fototrip.cli import main

    result = CliRunner().invoke(main, ["index", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "no built trips" in result.output.lower()


def test_the_cover_comes_from_the_middle_of_the_trip(tmp_path):
    """Not the first photo.

    Photos are ordered by capture time, so the first is whatever was shot on
    the way out -- an airport, a boarding pass, the first meal. The middle of
    the trip is where the trip actually is.
    """
    folder = tmp_path / "iceland"
    folder.mkdir()
    (folder / "photos.json").write_text(
        json.dumps(
            {
                "title": "Iceland",
                "photos": [{"id": f"IMG_{i}", "thumb": f"thumb/IMG_{i}.jpg"} for i in range(5)],
                "days": [{"day": "2024-05-01", "count": 5}],
            }
        ),
        encoding="utf-8",
    )

    [trip] = find_trips(tmp_path)

    assert trip.cover == "iceland/thumb/IMG_2.jpg"


def test_the_cover_prefers_the_lightbox_image_over_the_thumbnail(tmp_path):
    """Thumbnails are 96 px square; a card is several hundred wide."""
    folder = tmp_path / "iceland"
    folder.mkdir()
    (folder / "photos.json").write_text(
        json.dumps(
            {
                "title": "Iceland",
                "photos": [{"id": "IMG_1", "thumb": "thumb/IMG_1.jpg", "web": "web/IMG_1.jpg"}],
                "days": [{"day": "2024-05-01", "count": 1}],
            }
        ),
        encoding="utf-8",
    )

    [trip] = find_trips(tmp_path)

    assert trip.cover == "iceland/web/IMG_1.jpg"


def test_the_cover_is_lazily_loaded(tmp_path):
    """An overview over many trips must not fetch every full-size image at once."""
    trips = [
        Trip(
            title="Iceland",
            href="iceland/",
            cover="iceland/web/a.jpg",
            first_day="2024-05-01",
            last_day="2024-05-01",
            photos=1,
            days=1,
            subtitle="",
        ),
    ]

    render_overview(trips, tmp_path, title="Our trips")

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'loading="lazy"' in html


def test_the_overview_carries_no_inline_style(tmp_path):
    """Its stylesheet is a file, so `style-src 'self'` suffices."""
    render_overview([], tmp_path, title="Our trips")

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<style" not in html
    assert "style=" not in html
    assert 'href="overview.css"' in html
    assert (tmp_path / "overview.css").exists()


def test_the_overview_stylesheet_is_refreshed_on_every_run(tmp_path):
    """A stale stylesheet beside a new page is a confusing way to fail."""
    (tmp_path / "overview.css").write_text("/* from an older version */", encoding="utf-8")

    render_overview([], tmp_path, title="Our trips")

    assert "older version" not in (tmp_path / "overview.css").read_text(encoding="utf-8")


def test_the_folder_can_carry_its_own_title(tmp_path):
    """So a deploy does not have to repeat it on every run.

    Mirrors trip.toml for a single trip: the file names it, the flag overrides.
    """
    from fototrip.overview import OverviewConfig

    (tmp_path / "trips.toml").write_text(
        'title = "Lackas Family Trips"\nsubtitle = "where we went"\n', encoding="utf-8"
    )

    config = OverviewConfig.load(tmp_path)

    assert (config.title, config.subtitle) == ("Lackas Family Trips", "where we went")


def test_the_flag_wins_over_the_file(tmp_path):
    from fototrip.overview import OverviewConfig

    (tmp_path / "trips.toml").write_text('title = "From the file"\n', encoding="utf-8")

    assert OverviewConfig.load(tmp_path, title="From the flag").title == "From the flag"


def test_without_a_file_the_title_is_the_folder_name(tmp_path):
    from fototrip.overview import OverviewConfig

    folder = tmp_path / "our-trips"
    folder.mkdir()

    assert OverviewConfig.load(folder).title == "our-trips"


def test_the_subtitle_reaches_the_page(tmp_path):
    render_overview([], tmp_path, title="Lackas Family Trips", subtitle="ten years of it")

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "ten years of it" in html
