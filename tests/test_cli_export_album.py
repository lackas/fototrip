from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from fototrip import album
from fototrip.album import ExportRefused, ExportReport
from fototrip.cli import main

# The shape osxphotos 0.77.2 really writes, abbreviated to the columns the parser
# reads. tests/test_album.py holds the verbatim original and how to regenerate it.
REAL_HEADER = (
    "datetime,filename,exported,new,updated,skipped,exif_updated,touched,"
    "converted_to_jpeg,missing,error\n"
)
REAL_ROW = "2026-09-28T22:11:03.120954,/x/a.jpeg,1,0,0,0,0,0,1,0,\n"


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

    result = CliRunner().invoke(
        main,
        [
            "export-album",
            "A",
            "-o",
            str(tmp_path / "trip"),
            "--replace",
            "--expect",
            "9",
            "--jpeg-quality",
            "0.75",
            "--osxphotos",
            "/opt/homebrew/bin/osxphotos",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen["replace"] is True
    assert seen["in_album"] == 9
    assert seen["jpeg_quality"] == 0.75
    assert seen["osxphotos"] == "/opt/homebrew/bin/osxphotos"


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


def test_a_destination_that_is_a_file_is_refused_by_click(tmp_path):
    """Click refuses it before album.py is reached; album.py refuses it too."""
    not_a_folder = tmp_path / "trip"
    not_a_folder.write_bytes(b"not a folder")

    result = CliRunner().invoke(main, ["export-album", "A", "-o", str(not_a_folder)])

    assert result.exit_code != 0
    assert "file" in result.output.lower()
    assert not_a_folder.read_bytes() == b"not a folder"


def test_a_jpeg_quality_outside_the_range_is_refused_immediately(tmp_path):
    """A typo must not cost forty seconds of exporting first."""
    result = CliRunner().invoke(
        main, ["export-album", "A", "-o", str(tmp_path / "trip"), "--jpeg-quality", "95"]
    )
    assert result.exit_code != 0
    assert "0" in result.output and "1" in result.output


def test_the_command_really_fills_the_folder(tmp_path, monkeypatch):
    """The only end-to-end path: the real export_album, driven by the real command.

    Everything else in this file replaces export_album with a stand-in, so
    nothing else would notice if the command stopped wiring it up correctly.
    Only the two things that touch the outside world are faked: osxphotos, and
    the free-space reading, so the result does not depend on this machine's disk.
    """

    def fake_osxphotos(command):
        destination = Path(command[2])
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("IMG_1.jpg", "IMG_2.jpg"):
            (destination / name).write_bytes(b"jpegdata")
        Path(command[command.index("--report") + 1]).write_text(
            REAL_HEADER + REAL_ROW * 2, encoding="utf-8"
        )
        return 0

    monkeypatch.setattr("fototrip.cli.require_tools", lambda osxphotos="osxphotos": None)
    monkeypatch.setattr("fototrip.cli.run_osxphotos", fake_osxphotos)
    monkeypatch.setattr(
        album.shutil, "disk_usage", lambda path: SimpleNamespace(total=0, used=0, free=10**12)
    )

    target = tmp_path / "trip"
    result = CliRunner().invoke(main, ["export-album", "A", "-o", str(target), "--expect", "2"])

    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in target.iterdir()) == ["IMG_1.jpg", "IMG_2.jpg"]
    assert '2 photos in album "A"' in result.output
    assert "2 exported" in result.output
    assert "accounted for" not in result.output
    assert "is ready to build" in result.output
    # The staging folder and the run report are gone once the swap succeeded.
    assert not (tmp_path / "trip.incoming").exists()
    assert not (tmp_path / "trip.report.csv").exists()
