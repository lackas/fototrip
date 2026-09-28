from pathlib import Path

from click.testing import CliRunner

from fototrip.album import ExportRefused, ExportReport
from fototrip.cli import main


def test_export_album_reports_what_it_did(tmp_path, monkeypatch):
    def fake_export(album, destination, **kwargs):
        Path(destination).mkdir(parents=True, exist_ok=True)
        return ExportReport(album=album, in_album=3, exported=3, bytes_written=3_000_000)

    monkeypatch.setattr("fototrip.cli.require_tools", lambda osxphotos="osxphotos": None)
    monkeypatch.setattr("fototrip.cli.export_album", fake_export)

    result = CliRunner().invoke(
        main, ["export-album", "2026-07 Argentina", "-o", str(tmp_path / "trip"), "--expect", "3"]
    )

    assert result.exit_code == 0, result.output
    assert "3 exported" in result.output


def test_a_refusal_exits_non_zero_with_its_message(tmp_path, monkeypatch):
    def refuse(album, destination, **kwargs):
        raise ExportRefused("Not enough space: about 4.0 GB needed, 1.0 GB free.")

    monkeypatch.setattr("fototrip.cli.require_tools", lambda osxphotos="osxphotos": None)
    monkeypatch.setattr("fototrip.cli.export_album", refuse)

    result = CliRunner().invoke(main, ["export-album", "A", "-o", str(tmp_path / "trip")])

    assert result.exit_code != 0
    assert "Not enough space" in result.output


def test_a_missing_tool_exits_non_zero_with_the_instruction(tmp_path, monkeypatch):
    def missing(osxphotos="osxphotos"):
        raise ExportRefused("osxphotos not found. Install it with: ...")

    monkeypatch.setattr("fototrip.cli.require_tools", missing)

    result = CliRunner().invoke(main, ["export-album", "A", "-o", str(tmp_path / "trip")])

    assert result.exit_code != 0
    assert "osxphotos not found" in result.output


def test_replace_is_passed_through(tmp_path, monkeypatch):
    seen = {}

    def capture(album, destination, **kwargs):
        seen.update(kwargs)
        Path(destination).mkdir(parents=True, exist_ok=True)
        return ExportReport(album=album, in_album=1, exported=1)

    monkeypatch.setattr("fototrip.cli.require_tools", lambda osxphotos="osxphotos": None)
    monkeypatch.setattr("fototrip.cli.export_album", capture)

    CliRunner().invoke(
        main, ["export-album", "A", "-o", str(tmp_path / "trip"), "--replace", "--expect", "9"]
    )

    assert seen["replace"] is True
    assert seen["in_album"] == 9


def test_without_expect_the_free_space_check_is_announced_as_off(tmp_path, monkeypatch):
    monkeypatch.setattr("fototrip.cli.require_tools", lambda osxphotos="osxphotos": None)
    monkeypatch.setattr(
        "fototrip.cli.export_album",
        lambda album, destination, **kwargs: (
            Path(destination).mkdir(parents=True, exist_ok=True),
            ExportReport(album=album, in_album=0, exported=1),
        )[1],
    )

    result = CliRunner().invoke(main, ["export-album", "A", "-o", str(tmp_path / "trip")])

    assert "--expect" in result.output
    assert "free-space check is off" in result.output
    # The run-report check is NOT switched off with it, and the message must not imply it is.
    assert "still verified" in result.output


def test_the_build_command_still_works(tmp_path, make_jpeg):
    """This task must not disturb the pipeline it sits next to."""
    trip = make_jpeg("IMG_1.jpeg").parent
    out = tmp_path / "site"
    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])
    assert result.exit_code == 0, result.output
