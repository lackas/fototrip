import json

from click.testing import CliRunner

from fototrip.cli import main
from tests.conftest import BUENOS_AIRES, COLOGNE, IGUAZU


def test_build_produces_a_working_site(make_jpeg, tmp_path):
    trip = make_jpeg("IMG_1.jpeg", lat=COLOGNE[0], lon=COLOGNE[1]).parent
    make_jpeg("IMG_2.jpeg", lat=IGUAZU[0], lon=IGUAZU[1], stamp="2026:07:19 15:12:12")
    out = tmp_path / "site"

    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])

    assert result.exit_code == 0, result.output
    manifest = json.loads((out / "photos.json").read_text())
    assert len(manifest["photos"]) == 2
    assert [d["day"] for d in manifest["days"]] == ["2026-07-17", "2026-07-19"]
    for entry in manifest["photos"]:
        assert (out / entry["thumb"]).exists()
        assert (out / entry["web"]).exists()


def test_build_reports_skips_without_failing(make_jpeg, tmp_path):
    trip = make_jpeg("good.jpeg").parent
    make_jpeg("nogps.jpeg", lat=None, lon=None)
    make_jpeg("nostamp.jpeg", stamp=None)
    out = tmp_path / "site"

    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])

    assert result.exit_code == 0
    assert "1 photo" in result.output
    assert "no GPS coordinates" in result.output
    assert "no capture timestamp" in result.output
    assert len(json.loads((out / "photos.json").read_text())["photos"]) == 1


def test_second_build_serves_derivatives_from_cache(make_jpeg, tmp_path):
    trip = make_jpeg("IMG_1.jpeg").parent
    out = tmp_path / "site"
    CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])
    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])
    assert "1 cached" in result.output


def test_new_file_after_a_build_is_picked_up(make_jpeg, tmp_path):
    trip = make_jpeg("IMG_1.jpeg").parent
    out = tmp_path / "site"
    CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])
    make_jpeg("IMG_2.jpeg", lat=BUENOS_AIRES[0], lon=BUENOS_AIRES[1])
    CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])
    assert len(json.loads((out / "photos.json").read_text())["photos"]) == 2


def test_truncated_file_is_skipped_then_included_once_complete(make_jpeg, tmp_path):
    """Mirrors building while Photos is still writing the folder."""
    trip = make_jpeg("IMG_1.jpeg").parent
    complete = make_jpeg("IMG_2.jpeg", lat=IGUAZU[0], lon=IGUAZU[1])
    payload = complete.read_bytes()
    complete.write_bytes(payload[:120])
    out = tmp_path / "site"

    first = CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])
    assert "unreadable or truncated image" in first.output
    assert len(json.loads((out / "photos.json").read_text())["photos"]) == 1

    complete.write_bytes(payload)
    CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])
    assert len(json.loads((out / "photos.json").read_text())["photos"]) == 2


def test_empty_folder_exits_nonzero_with_a_clear_message(tmp_path):
    trip = tmp_path / "empty"
    trip.mkdir()
    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(tmp_path / "site")])
    assert result.exit_code != 0
    assert "no photos" in result.output.lower()


def test_missing_folder_exits_nonzero(tmp_path):
    result = CliRunner().invoke(main, ["build", str(tmp_path / "nope"), "-o", str(tmp_path / "s")])
    assert result.exit_code != 0


def test_title_flag_overrides_the_folder_name(make_jpeg, tmp_path):
    trip = make_jpeg("IMG_1.jpeg").parent
    out = tmp_path / "site"
    CliRunner().invoke(main, ["build", str(trip), "-o", str(out), "--title", "Argentina 2026"])
    assert "<title>Argentina 2026</title>" in (out / "index.html").read_text()
