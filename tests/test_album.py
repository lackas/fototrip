import shutil
import sys
from collections import Counter
from pathlib import Path

import pytest

from fototrip import album
from fototrip.album import (
    MEGABYTES_PER_PHOTO,
    MINIMUM_FREE_BYTES,
    ExportReport,
    ExportRefused,
    _human_bytes,
    build_command,
    export_album,
    read_osxphotos_report,
    require_tools,
    run_osxphotos,
)


def test_report_names_the_album_and_the_counts():
    report = ExportReport(album="2026-07 Argentina", in_album=2563, exported=2551)
    rendered = report.render()
    assert '2563 photos in album "2026-07 Argentina"' in rendered
    assert "2551 exported" in rendered


def test_the_report_says_how_many_photos_the_run_never_mentioned():
    """The invariant is exported + skipped == the album's size.

    The feature exists because ten days of a trip were missing and nothing in
    the build could tell "not exported" from "not taken".
    """
    report = ExportReport(album="A", in_album=10, exported=7)
    report.failed["export failed"] = 1
    rendered = report.render()
    assert "2 not accounted for by the run report" in rendered


def test_the_report_stays_quiet_when_every_photo_is_accounted_for():
    report = ExportReport(album="A", in_album=3, exported=2)
    report.failed["could not download"] = 1
    assert "accounted for" not in report.render()


def test_the_report_says_so_when_more_files_came_out_than_the_album_holds():
    """More than the album holds means the export wrote a photo twice."""
    rendered = ExportReport(album="A", in_album=2, exported=3).render()
    assert "1 more files than the album holds" in rendered


def test_report_lists_failures_with_their_reason():
    report = ExportReport(album="A", in_album=3, exported=1)
    report.failed["export failed"] = 2
    rendered = report.render()
    assert "2 skipped:" in rendered
    assert "export failed" in rendered


def test_report_omits_the_failure_block_when_nothing_failed():
    assert "skipped" not in ExportReport(album="A", in_album=1, exported=1).render()


def test_report_shows_a_human_readable_size():
    report = ExportReport(album="A", in_album=1, exported=1, bytes_written=4_900_000_000)
    assert "4.9 GB" in report.render()


def test_report_size_stays_readable_for_small_exports():
    report = ExportReport(album="A", in_album=1, exported=1, bytes_written=3_500_000)
    assert "3.5 MB" in report.render()


def test_report_omits_the_album_size_when_it_is_unknown():
    """The size is only known when the user supplies it, so 0 means unknown."""
    rendered = ExportReport(album="A", in_album=0, exported=3).render()
    assert "0 photos" not in rendered
    assert "3 exported" in rendered


def test_report_omits_size_line_when_bytes_written_is_zero():
    """Size line is only added when bytes_written is nonzero."""
    rendered = ExportReport(album="A", in_album=1, exported=1, bytes_written=0).render()
    assert "written" not in rendered


# Human bytes boundary tests pinning unit promotion
def test_human_bytes_zero():
    """Zero bytes renders as whole number."""
    assert _human_bytes(0) == "0 B"


def test_human_bytes_bytes_stay_whole():
    """Byte values render without decimal places."""
    assert _human_bytes(847) == "847 B"
    assert _human_bytes(999) == "999 B"


def test_human_bytes_boundary_bytes_to_kb():
    """Promotion from bytes to kB happens at 1000."""
    assert _human_bytes(999) == "999 B"
    assert _human_bytes(1000) == "1.0 kB"


def test_human_bytes_kb_gets_one_decimal():
    """kilobytes render with one decimal place."""
    assert _human_bytes(3500) == "3.5 kB"


def test_human_bytes_boundary_kb_to_mb():
    """Promotion from kB to MB based on formatted value (1000 kB = 1.0 MB)."""
    assert _human_bytes(999_999) == "1.0 MB"
    assert _human_bytes(1_000_000) == "1.0 MB"


def test_human_bytes_mb_with_one_decimal():
    """Megabytes render with one decimal."""
    assert _human_bytes(3_500_000) == "3.5 MB"


def test_human_bytes_large_gb():
    """Large gigabytes render correctly (typical export size for this feature)."""
    assert _human_bytes(2_700_000_000) == "2.7 GB"


def test_human_bytes_boundary_gb_to_tb():
    """Promotion from GB to TB based on formatted value."""
    # 999_900_000_000 bytes = 999.9 GB, which formats as "999.9 GB"
    # This stays in GB; anything that would format as 1000+ GB promotes to TB
    assert _human_bytes(999_900_000_000) == "999.9 GB"
    # 1_000_000_000_000 bytes = 1000 GB = 1.0 TB
    assert _human_bytes(1_000_000_000_000) == "1.0 TB"


def test_human_bytes_above_terabyte():
    """Values above terabyte render in TB (last unit)."""
    assert _human_bytes(5_500_000_000_000) == "5.5 TB"


def _command(album="2026-07 Argentina", **kwargs):
    return build_command(album, Path("/tmp/out.incoming"), Path("/tmp/report.csv"), **kwargs)


def test_command_exports_the_named_album_to_the_destination():
    command = _command()
    assert command[0] == "osxphotos"
    assert command[1] == "export"
    assert "/tmp/out.incoming" in command
    assert command[command.index("--album") + 1] == "2026-07 Argentina"


def test_command_converts_to_jpeg_and_writes_metadata():
    command = _command()
    assert "--convert-to-jpeg" in command
    assert "--exiftool" in command
    assert command[command.index("--jpeg-quality") + 1] == "0.9"


def test_command_takes_photos_only_and_no_live_motion():
    command = _command()
    assert "--only-photos" in command
    assert "--skip-live" in command


def test_command_produces_one_file_per_album_photo():
    """Every osxphotos default that would write a second file for one photo.

    Without these, an edited photo exports twice, a burst exports every frame,
    and a RAW+JPEG pair exports both -- and each duplicate becomes its own pin
    on the map, at the same place and the same second.
    """
    command = _command()
    for flag in ("--skip-live", "--skip-original-if-edited", "--skip-bursts", "--skip-raw"):
        assert flag in command, flag


def test_command_downloads_missing_originals_and_asks_for_a_report():
    command = _command()
    assert "--download-missing" in command
    assert command[command.index("--report") + 1] == "/tmp/report.csv"


def test_command_never_writes_to_the_library():
    """The library is read-only. No flag may put anything back into Photos."""
    forbidden = {
        "--add-exported-to-album",
        "--add-skipped-to-album",
        "--add-missing-to-album",
        "--post-command",
        "--post-function",
        "--run-command",
    }
    assert forbidden.isdisjoint(_command())


def test_an_album_name_that_looks_like_a_flag_stays_an_argument():
    """A hostile or merely odd album name must never become another option."""
    command = build_command('--delete-file"; rm -rf /', Path("/tmp/out"), Path("/tmp/r.csv"))
    assert command[command.index("--album") + 1] == '--delete-file"; rm -rf /'
    assert command.count("--album") == 1
    assert "--delete-file" not in command


def test_a_multiline_album_name_is_still_one_argument():
    command = build_command("line one\nline two", Path("/tmp/out"), Path("/tmp/r.csv"))
    assert command[command.index("--album") + 1] == "line one\nline two"


def test_the_osxphotos_executable_can_be_overridden():
    command = _command(osxphotos="/opt/homebrew/bin/osxphotos")
    assert command[0] == "/opt/homebrew/bin/osxphotos"


def _write_report(tmp_path, rows):
    path = tmp_path / "report.csv"
    path.write_text(REAL_OSXPHOTOS_HEADER + "".join(rows), encoding="utf-8")
    return path


def test_exported_rows_are_counted(tmp_path):
    path = _write_report(tmp_path, [_real_row(), _real_row()])
    report = ExportReport(album="A")
    read_osxphotos_report(path, report)
    assert report.exported == 2
    assert report.failed == Counter()


def test_rows_with_an_error_are_counted_as_failures_with_their_message(tmp_path):
    path = _write_report(
        tmp_path,
        [_real_row(), _real_row(exported=False, error="could not download")],
    )
    report = ExportReport(album="A")
    read_osxphotos_report(path, report)
    assert report.exported == 1
    assert report.failed["could not download"] == 1


def test_a_row_that_neither_exported_nor_errored_is_counted_as_failed(tmp_path):
    """Silence is not success: an unexported photo with no message still missed."""
    path = _write_report(tmp_path, [_real_row(exported=False)])
    report = ExportReport(album="A")
    read_osxphotos_report(path, report)
    assert report.exported == 0
    assert report.failed["export failed"] == 1


def test_the_boolean_spelling_is_accepted_too():
    """osxphotos' JSON writer passes bool_values=True and emits True/False.

    Only the CSV writer emits 1/0. Accepting both costs nothing and means a
    future switch of writers cannot silently zero the counts.
    """
    assert album._is_true("True")
    assert not album._is_true("False")


def test_a_missing_report_leaves_the_counts_alone(tmp_path):
    report = ExportReport(album="A", exported=7)
    read_osxphotos_report(tmp_path / "nope.csv", report)
    assert report.exported == 7


def test_an_unparsable_report_leaves_the_counts_alone(tmp_path):
    path = tmp_path / "report.csv"
    path.write_bytes(b"\xff\xfe not a csv at all")
    report = ExportReport(album="A", exported=7)
    read_osxphotos_report(path, report)
    assert report.exported == 7


def test_an_unexpected_column_layout_does_not_raise(tmp_path):
    """osxphotos may add or reorder columns between versions."""
    path = tmp_path / "report.csv"
    path.write_text("something,else\n1,2\n", encoding="utf-8")
    report = ExportReport(album="A")
    read_osxphotos_report(path, report)
    assert report.exported == 0
    assert report.failed == Counter()


# A report produced by osxphotos 0.77.2 itself, pasted verbatim. Regenerate with:
#   from osxphotos.cli.report_writer import ExportReportWriterCSV
#   from osxphotos.photoexporter import ExportResults
#   r = ExportResults(); r.exported = ["/x/a.jpeg"]; r.converted_to_jpeg = ["/x/a.jpeg"]
#   w = ExportReportWriterCSV(path); w.write(r); w.close()
# The values are 1/0, NOT True/False: only osxphotos' JSON writer passes
# bool_values=True. A parser written against the wrong one counts every
# successful export as a failure and silently disables the truncation gate.
REAL_OSXPHOTOS_HEADER = (
    "datetime,filename,exported,new,updated,skipped,exif_updated,touched,"
    "converted_to_jpeg,sidecar_xmp,sidecar_json,sidecar_exiftool,missing,error,"
    "exiftool_warning,exiftool_error,extended_attributes_written,"
    "extended_attributes_skipped,cleanup_deleted_file,cleanup_deleted_directory,"
    "exported_album,sidecar_user,sidecar_user_error,user_written,user_skipped,"
    "user_error,aae_written,aae_skipped\n"
)
REAL_EXPORTED_ROW = (
    "2026-09-28T22:11:03.120954,/x/a.jpeg,1,0,0,0,0,0,1,0,0,0,0,,,,0,0,0,0,,0,,0,0,,0,0\n"
)


def _real_row(exported=True, error=""):
    """One row in the format osxphotos actually writes.

    Column order and count come from REAL_OSXPHOTOS_HEADER; only `exported` and
    `error` are ever read, but the row has to be the real width so a parser that
    depends on position rather than on the header cannot pass.
    """
    columns = REAL_OSXPHOTOS_HEADER.rstrip("\n").split(",")
    row = ["0"] * len(columns)
    row[columns.index("datetime")] = "2026-09-28T22:11:03.120954"
    row[columns.index("filename")] = "/x/a.jpeg"
    row[columns.index("exported")] = "1" if exported else "0"
    row[columns.index("error")] = error
    return ",".join(row) + "\n"


def test_a_report_in_the_format_osxphotos_actually_writes_is_counted(tmp_path):
    """The format is 1/0, not True/False.

    Written against a hand-invented header, the parser counted every successful
    export as a failure and left `exported` at 0, which made the truncation gate
    in export_album vacuous.
    """
    path = tmp_path / "report.csv"
    path.write_text(REAL_OSXPHOTOS_HEADER + REAL_EXPORTED_ROW * 3, encoding="utf-8")
    report = ExportReport(album="A")
    read_osxphotos_report(path, report)
    assert report.exported == 3
    assert report.failed == Counter()


def test_hidden_files_and_appledouble_sidecars_are_not_counted_as_photos(tmp_path):
    """The count must agree with scan.find_photos, which excludes these.

    Counting a file the build will not include biases the swap gate toward
    accepting a short export.
    """
    (tmp_path / "real.jpg").write_bytes(b"jpegdata")
    (tmp_path / "._IMG_1.jpg").write_bytes(b"appledouble")
    (tmp_path / ".hidden.jpg").write_bytes(b"hidden")
    (tmp_path / ".thumbnails").mkdir()
    (tmp_path / ".thumbnails" / "IMG_1.jpg").write_bytes(b"cached")

    assert [p.name for p in album._image_files(tmp_path)] == ["real.jpg"]


# Real bytes, not mocks: the whole point of _normalise_extensions is that content
# decides and the extension does not.
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
HEIC_BYTES = b"\x00\x00\x00\x20ftypheic" + b"\x00" * 32
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_a_jpeg_wearing_a_heic_name_is_renamed(tmp_path):
    """An iCloud Shared Album hands out JPEG bytes under the original HEIC name.

    1170 of one real album's 2563 photos, so --convert-to-jpeg had nothing to
    convert and kept the name.
    """
    (tmp_path / "IMG_1.HEIC").write_bytes(JPEG_BYTES)

    assert album._normalise_extensions(tmp_path) == 1
    assert (tmp_path / "IMG_1.jpeg").read_bytes() == JPEG_BYTES
    assert not (tmp_path / "IMG_1.HEIC").exists()


def test_a_genuine_heic_keeps_its_name(tmp_path):
    """Content decides. A real HEIC must still fail the count and refuse the swap."""
    (tmp_path / "IMG_2.HEIC").write_bytes(HEIC_BYTES)

    assert album._normalise_extensions(tmp_path) == 0
    assert (tmp_path / "IMG_2.HEIC").read_bytes() == HEIC_BYTES


def test_a_real_png_keeps_its_name(tmp_path):
    """PNG is a format the build handles; renaming it would be a lie about its bytes."""
    (tmp_path / "IMG_3.PNG").write_bytes(PNG_BYTES)

    assert album._normalise_extensions(tmp_path) == 0
    assert (tmp_path / "IMG_3.PNG").read_bytes() == PNG_BYTES


def test_a_rename_never_overwrites_an_existing_file(tmp_path):
    """Two library assets can share a stem, and one of them must not eat the other."""
    (tmp_path / "IMG_4.HEIC").write_bytes(JPEG_BYTES)
    (tmp_path / "IMG_4.jpeg").write_bytes(b"\xff\xd8\xffalready here")

    assert album._normalise_extensions(tmp_path) == 1
    assert (tmp_path / "IMG_4.jpeg").read_bytes() == b"\xff\xd8\xffalready here"
    assert (tmp_path / "IMG_4-1.jpeg").read_bytes() == JPEG_BYTES


def test_the_osxphotos_export_database_is_left_alone(tmp_path):
    """osxphotos writes .osxphotos_export.db into the destination; it is not a photo."""
    database = tmp_path / ".osxphotos_export.db"
    database.write_bytes(b"\xff\xd8\xffnot really a jpeg")

    assert album._normalise_extensions(tmp_path) == 0
    assert database.exists()


HUGE = 10**12


def _runner_that_writes(files=("a.jpg",), exit_code=0, report_rows=None):
    """A stand-in osxphotos: writes files into the destination, then exits.

    It deliberately does NOT create the destination. osxphotos declares its
    DEST argument `exists=True` and refuses a directory that is not already
    there, so a double that mkdirs it would hide the caller's obligation --
    which is exactly how `export_album` reached eleven commits unable to run
    against the real tool even once.
    """

    def run(command):
        destination = Path(command[2])
        assert destination.is_dir(), (
            f"osxphotos requires DEST to exist before it runs: {destination}"
        )
        for name in files:
            (destination / name).write_bytes(b"jpegdata")
        report_path = Path(command[command.index("--report") + 1])
        rows = report_rows if report_rows is not None else [_real_row() for _ in files]
        report_path.write_text(REAL_OSXPHOTOS_HEADER + "".join(rows), encoding="utf-8")
        return exit_code

    return run


def test_a_successful_export_replaces_the_target(tmp_path):
    target = tmp_path / "trip"
    target.mkdir()
    (target / "old.jpeg").write_bytes(b"old")

    report = export_album(
        "A",
        target,
        in_album=2,
        replace=True,
        runner=_runner_that_writes(("new1.jpg", "new2.jpg")),
        free_space=lambda p: HUGE,
    )

    assert sorted(p.name for p in target.iterdir()) == ["new1.jpg", "new2.jpg"]
    assert not (tmp_path / "trip.incoming").exists()
    assert report.exported == 2


def test_a_non_empty_target_without_replace_is_refused(tmp_path):
    target = tmp_path / "trip"
    target.mkdir()
    (target / "old.jpeg").write_bytes(b"old")

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A", target, in_album=1, runner=_runner_that_writes(), free_space=lambda p: HUGE
        )

    assert "--replace" in excinfo.value.message
    # Naming what is in the way, not just counting it.
    assert "old.jpeg" in excinfo.value.message
    assert (target / "old.jpeg").exists()


def test_an_empty_target_needs_no_replace_flag(tmp_path):
    target = tmp_path / "trip"
    target.mkdir()
    export_album("A", target, in_album=1, runner=_runner_that_writes(), free_space=lambda p: HUGE)
    assert (target / "a.jpg").exists()


def test_a_missing_target_is_created(tmp_path):
    target = tmp_path / "trip"
    export_album("A", target, in_album=1, runner=_runner_that_writes(), free_space=lambda p: HUGE)
    assert (target / "a.jpg").exists()


def test_a_failing_export_leaves_the_target_untouched(tmp_path):
    target = tmp_path / "trip"
    target.mkdir()
    (target / "old.jpeg").write_bytes(b"old")

    with pytest.raises(ExportRefused):
        export_album(
            "A",
            target,
            in_album=1,
            replace=True,
            runner=_runner_that_writes(("partial.jpg",), exit_code=1),
            free_space=lambda p: HUGE,
        )

    assert (target / "old.jpeg").read_bytes() == b"old"
    assert (tmp_path / "trip.incoming" / "partial.jpg").exists()


def test_an_export_that_produces_nothing_does_not_replace_anything(tmp_path):
    """osxphotos exits 0 for an album name it did not match. That is not success."""
    target = tmp_path / "trip"
    target.mkdir()
    (target / "old.jpeg").write_bytes(b"old")

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=1,
            replace=True,
            runner=lambda command: 0,
            free_space=lambda p: HUGE,
        )

    assert "no photos" in excinfo.value.message.lower()
    assert (target / "old.jpeg").exists()


def test_fewer_files_than_the_report_claims_does_not_replace_anything(tmp_path):
    """A run that says it exported more than it wrote does not get to swap."""
    target = tmp_path / "trip"
    target.mkdir()
    (target / "old.jpeg").write_bytes(b"old")

    rows = [_real_row() for _ in range(5)]
    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=5,
            replace=True,
            runner=_runner_that_writes(("only_one.jpg",), report_rows=rows),
            free_space=lambda p: HUGE,
        )

    assert (target / "old.jpeg").exists()
    assert "fewer" in excinfo.value.message.lower()


def test_a_short_export_is_refused_when_the_report_is_in_the_real_format(tmp_path):
    """The gate must fire on a real report, which is where it was dead."""
    target = tmp_path / "trip"
    target.mkdir()
    (target / "old.jpeg").write_bytes(b"old")

    def runner_claiming_five_writing_one(command):
        destination = Path(command[2])
        assert destination.is_dir(), (
            f"osxphotos requires DEST to exist before it runs: {destination}"
        )
        (destination / "only_one.jpg").write_bytes(b"jpegdata")
        Path(command[command.index("--report") + 1]).write_text(
            REAL_OSXPHOTOS_HEADER + REAL_EXPORTED_ROW * 5, encoding="utf-8"
        )
        return 0

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=5,
            replace=True,
            runner=runner_claiming_five_writing_one,
            free_space=lambda p: HUGE,
        )

    assert "fewer" in excinfo.value.message.lower()
    assert (target / "old.jpeg").read_bytes() == b"old"


def test_a_short_export_names_the_files_that_were_not_counted(tmp_path):
    """ "wrote fewer" alone sends someone looking through 2563 files for one.

    After the extension fix, the realistic cause is a file the export produced
    that `_image_files` does not recognise -- a format that came through
    unconverted -- so the refusal names it.
    """
    target = tmp_path / "trip"

    def runner_writing_an_unrecognised_format(command):
        destination = Path(command[2])
        assert destination.is_dir(), (
            f"osxphotos requires DEST to exist before it runs: {destination}"
        )
        (destination / "a.jpg").write_bytes(JPEG_BYTES)
        (destination / "b.tiff").write_bytes(b"not a jpg or png")
        Path(command[command.index("--report") + 1]).write_text(
            REAL_OSXPHOTOS_HEADER + REAL_EXPORTED_ROW * 2, encoding="utf-8"
        )
        return 0

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=2,
            runner=runner_writing_an_unrecognised_format,
            free_space=lambda p: HUGE,
        )

    assert "b.tiff" in excinfo.value.message


def test_jpegs_under_a_heic_name_do_not_block_the_swap(tmp_path):
    """The real bug: a perfect export was refused because 46% of it was miscounted.

    `_image_files` counts .jpg/.jpeg/.png, so HEIC-named JPEGs were invisible to
    the truncation gate and `len(written) < report.exported` refused a run that
    had exported everything.
    """
    target = tmp_path / "trip"

    def runner_writing_a_heic_named_jpeg(command):
        destination = Path(command[2])
        assert destination.is_dir(), (
            f"osxphotos requires DEST to exist before it runs: {destination}"
        )
        (destination / "a.jpg").write_bytes(JPEG_BYTES)
        (destination / "b.HEIC").write_bytes(JPEG_BYTES)
        Path(command[command.index("--report") + 1]).write_text(
            REAL_OSXPHOTOS_HEADER + REAL_EXPORTED_ROW * 2, encoding="utf-8"
        )
        return 0

    report = export_album(
        "A",
        target,
        in_album=2,
        runner=runner_writing_a_heic_named_jpeg,
        free_space=lambda p: HUGE,
    )

    assert sorted(p.name for p in target.iterdir()) == ["a.jpg", "b.jpeg"]
    assert report.exported == 2


def test_a_genuine_heic_still_refuses_the_swap(tmp_path):
    """The spec's "No HEIC file reaches the trip folder" must still hold."""
    target = tmp_path / "trip"
    target.mkdir()
    (target / "old.jpeg").write_bytes(b"old")

    def runner_writing_a_real_heic(command):
        destination = Path(command[2])
        assert destination.is_dir(), (
            f"osxphotos requires DEST to exist before it runs: {destination}"
        )
        (destination / "a.jpg").write_bytes(JPEG_BYTES)
        (destination / "b.HEIC").write_bytes(HEIC_BYTES)
        Path(command[command.index("--report") + 1]).write_text(
            REAL_OSXPHOTOS_HEADER + REAL_EXPORTED_ROW * 2, encoding="utf-8"
        )
        return 0

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=2,
            replace=True,
            runner=runner_writing_a_real_heic,
            free_space=lambda p: HUGE,
        )

    assert "fewer" in excinfo.value.message.lower()
    assert (target / "old.jpeg").read_bytes() == b"old"


def test_too_little_free_space_is_refused_before_exporting(tmp_path):
    target = tmp_path / "trip"
    ran = []

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=2563,
            runner=lambda command: ran.append(command) or 0,
            free_space=lambda p: 1_000_000,
        )

    assert ran == []
    assert "space" in excinfo.value.message.lower()
    # The album size is the figure the estimate came from, so it is named.
    assert "needed for 2563 photos" in excinfo.value.message
    assert not (tmp_path / "trip.incoming").exists()


def test_the_space_estimate_scales_with_the_album_size(tmp_path):
    """10_000 photos must need more room than 10 do.

    Both branches see the same free space, and it is deliberately above
    MINIMUM_FREE_BYTES: what separates them is the album size, not the floor.
    """
    target = tmp_path / "trip"
    free = MEGABYTES_PER_PHOTO * 1_000 * 1_000_000 * 2
    assert free > MINIMUM_FREE_BYTES
    export_album(
        "A",
        target,
        in_album=10,
        runner=_runner_that_writes(),
        free_space=lambda p: free,
    )
    with pytest.raises(ExportRefused):
        export_album(
            "A",
            tmp_path / "trip2",
            in_album=10_000,
            runner=_runner_that_writes(),
            free_space=lambda p: free,
        )


def test_refuses_to_replace_the_current_working_directory(tmp_path, monkeypatch):
    """Replacing the directory the process is sitting in breaks the process."""
    target = tmp_path / "trip"
    target.mkdir()
    (target / "old.jpeg").write_bytes(b"old")
    monkeypatch.chdir(target)

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=1,
            replace=True,
            runner=_runner_that_writes(),
            free_space=lambda p: HUGE,
        )

    assert "working directory" in excinfo.value.message.lower()
    assert (target / "old.jpeg").exists()


def test_an_unwritable_parent_is_refused_with_a_clear_message(tmp_path):
    parent = tmp_path / "locked"
    parent.mkdir(mode=0o500)
    try:
        with pytest.raises(ExportRefused) as excinfo:
            export_album(
                "A",
                parent / "trip",
                in_album=1,
                runner=_runner_that_writes(),
                free_space=lambda p: HUGE,
            )
        assert "writ" in excinfo.value.message.lower()
    finally:
        parent.chmod(0o700)


def test_a_stale_incoming_folder_from_an_earlier_run_is_cleared_first(tmp_path):
    target = tmp_path / "trip"
    stale = tmp_path / "trip.incoming"
    stale.mkdir()
    (stale / "leftover.jpg").write_bytes(b"stale")

    export_album(
        "A",
        target,
        in_album=1,
        runner=_runner_that_writes(("fresh.jpg",)),
        free_space=lambda p: HUGE,
    )

    assert sorted(p.name for p in target.iterdir()) == ["fresh.jpg"]


def test_the_report_records_the_bytes_actually_written(tmp_path):
    target = tmp_path / "trip"
    report = export_album(
        "A",
        target,
        in_album=2,
        runner=_runner_that_writes(("a.jpg", "b.jpg")),
        free_space=lambda p: HUGE,
    )
    assert report.bytes_written == len(b"jpegdata") * 2


def test_the_old_folder_is_deleted_only_after_the_new_one_is_in_place(tmp_path, monkeypatch):
    """The swap must never leave the target missing.

    The old folder is renamed aside and deleted only once the export is already
    in place, so an interruption leaves either the complete old folder or the
    complete new one.
    """
    target = tmp_path / "trip"
    target.mkdir()
    (target / "old.jpeg").write_bytes(b"old")

    contents_at_each_delete = []
    real_rmtree = shutil.rmtree

    def recording_rmtree(path, *args, **kwargs):
        contents_at_each_delete.append(
            sorted(p.name for p in target.iterdir()) if target.is_dir() else None
        )
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(album.shutil, "rmtree", recording_rmtree)

    export_album(
        "A",
        target,
        in_album=1,
        replace=True,
        runner=_runner_that_writes(("new.jpg",)),
        free_space=lambda p: HUGE,
    )

    assert (target / "new.jpg").exists()
    assert contents_at_each_delete[-1] == ["new.jpg"]


def test_a_leftover_previous_folder_is_refused_rather_than_deleted(tmp_path):
    """`.previous` may be the only surviving copy of the old folder.

    An interrupted swap leaves the old trip folder there and nowhere else, so a
    later run must stop and say so instead of quietly deleting it.
    """
    target = tmp_path / "trip"
    target.mkdir()
    leftover = tmp_path / "trip.previous"
    leftover.mkdir()
    (leftover / "the_only_copy.jpeg").write_bytes(b"irreplaceable")

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=1,
            replace=True,
            runner=_runner_that_writes(("new.jpg",)),
            free_space=lambda p: HUGE,
        )

    assert "trip.previous" in excinfo.value.message
    assert (leftover / "the_only_copy.jpeg").read_bytes() == b"irreplaceable"
    assert not (tmp_path / "trip.incoming").exists()


def test_a_run_whose_report_cannot_be_read_does_not_replace_anything(tmp_path):
    """Without a readable report there is no truncation check, so do not swap.

    A forgiving parser leaves `exported` at 0, which would make the
    `len(written) < exported` gate vacuously true and let a partial export
    through.
    """
    target = tmp_path / "trip"
    target.mkdir()
    (target / "old.jpeg").write_bytes(b"old")

    def runner_that_writes_no_report(command):
        destination = Path(command[2])
        assert destination.is_dir(), (
            f"osxphotos requires DEST to exist before it runs: {destination}"
        )
        (destination / "one_of_many.jpg").write_bytes(b"jpegdata")
        return 0

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=2563,
            replace=True,
            runner=runner_that_writes_no_report,
            free_space=lambda p: HUGE,
        )

    assert "could not be read" in excinfo.value.message
    assert (target / "old.jpeg").read_bytes() == b"old"


def test_a_failed_move_into_place_puts_the_old_folder_back(tmp_path, monkeypatch):
    """The old folder must be restored, not left under its staging name."""
    target = tmp_path / "trip"
    target.mkdir()
    (target / "old.jpeg").write_bytes(b"old")

    real_rename = Path.rename

    def rename(self, other):
        if Path(other) == target and self.name.endswith(".incoming"):
            raise OSError("no")
        return real_rename(self, other)

    monkeypatch.setattr(Path, "rename", rename)

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=1,
            replace=True,
            runner=_runner_that_writes(("new.jpg",)),
            free_space=lambda p: HUGE,
        )

    assert "could not move the export into place" in excinfo.value.message.lower()
    assert (target / "old.jpeg").read_bytes() == b"old"
    assert not (tmp_path / "trip.previous").exists()


def test_refuses_to_replace_a_parent_of_the_current_working_directory(tmp_path, monkeypatch):
    target = tmp_path / "trip"
    (target / "sub").mkdir(parents=True)
    (target / "old.jpeg").write_bytes(b"old")
    monkeypatch.chdir(target / "sub")

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=1,
            replace=True,
            runner=_runner_that_writes(),
            free_space=lambda p: HUGE,
        )

    assert "working directory" in excinfo.value.message.lower()
    assert (target / "old.jpeg").exists()


def test_too_little_free_space_is_refused_even_without_expect(tmp_path):
    """The spec's space check is unconditional; --expect only makes it sharper."""
    ran = []
    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            tmp_path / "trip",
            in_album=0,
            runner=lambda command: ran.append(command) or 0,
            free_space=lambda p: 100_000_000,
        )
    assert ran == []
    assert "space" in excinfo.value.message.lower()
    # Nothing counted the album, so the message must not pretend something did.
    assert "0 photos" not in excinfo.value.message
    assert "at least" in excinfo.value.message


def test_a_staging_folder_that_cannot_be_cleared_is_refused(tmp_path, monkeypatch):
    """A partial clear would mix two albums in one folder, and pass the gate.

    Leftovers left beside the new export make `len(written) >= exported` easier
    to satisfy, so a suppressed rmtree error ends in a successful swap.
    """
    target = tmp_path / "trip"
    target.mkdir()
    (target / "old.jpeg").write_bytes(b"old")
    stale = tmp_path / "trip.incoming"
    stale.mkdir()
    (stale / "from_another_album.jpg").write_bytes(b"stale")

    def refusing_rmtree(path, *args, **kwargs):
        raise OSError("Operation not permitted")

    monkeypatch.setattr(album.shutil, "rmtree", refusing_rmtree)

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=1,
            replace=True,
            runner=_runner_that_writes(("new.jpg",)),
            free_space=lambda p: HUGE,
        )

    assert "trip.incoming" in excinfo.value.message
    assert (target / "old.jpeg").read_bytes() == b"old"
    assert (stale / "from_another_album.jpg").exists()


def test_a_staging_folder_that_is_a_symlink_is_refused(tmp_path):
    """rmtree refuses a symlink, and following it would delete someone's folder."""
    target = tmp_path / "trip"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "not_ours.jpg").write_bytes(b"keep")
    (tmp_path / "trip.incoming").symlink_to(elsewhere)

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=1,
            runner=_runner_that_writes(("new.jpg",)),
            free_space=lambda p: HUGE,
        )

    assert "trip.incoming" in excinfo.value.message
    assert (elsewhere / "not_ours.jpg").read_bytes() == b"keep"


def test_a_destination_that_is_a_file_is_refused(tmp_path):
    """A file slips every is_dir() guard and dies on the final rename instead.

    The refusal has to come before anything is staged: an hour of exporting
    followed by a bare NotADirectoryError is not a clear message.
    """
    target = tmp_path / "trip"
    target.write_bytes(b"not a folder")
    ran = []

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=1,
            replace=True,
            runner=lambda command: ran.append(command) or 0,
            free_space=lambda p: HUGE,
        )

    assert "not a directory" in excinfo.value.message.lower()
    assert ran == []
    assert not (tmp_path / "trip.incoming").exists()
    assert target.read_bytes() == b"not a folder"


def test_a_destination_that_is_a_symlink_to_a_directory_is_refused(tmp_path):
    """Renaming the link would put the photos on the parent's volume."""
    real = tmp_path / "photos_on_another_volume"
    real.mkdir()
    (real / "old.jpeg").write_bytes(b"old")
    target = tmp_path / "trip"
    target.symlink_to(real)

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=1,
            replace=True,
            runner=_runner_that_writes(),
            free_space=lambda p: HUGE,
        )

    assert "symlink" in excinfo.value.message.lower()
    assert target.is_symlink()
    assert (real / "old.jpeg").read_bytes() == b"old"


def test_a_rollback_that_also_fails_still_names_both_folders(tmp_path, monkeypatch):
    """Nothing is lost, but only a message can tell the user where it went."""
    target = tmp_path / "trip"
    target.mkdir()
    (target / "old.jpeg").write_bytes(b"old")

    real_rename = Path.rename

    def rename(self, other):
        if Path(other) == target:
            raise OSError("no")
        return real_rename(self, other)

    monkeypatch.setattr(Path, "rename", rename)

    with pytest.raises(ExportRefused) as excinfo:
        export_album(
            "A",
            target,
            in_album=1,
            replace=True,
            runner=_runner_that_writes(("new.jpg",)),
            free_space=lambda p: HUGE,
        )

    message = excinfo.value.message
    assert "could not put" in message.lower()
    assert str(tmp_path / "trip.previous") in message
    assert str(tmp_path / "trip.incoming") in message
    assert (tmp_path / "trip.previous" / "old.jpeg").read_bytes() == b"old"
    assert (tmp_path / "trip.incoming" / "new.jpg").exists()


def test_free_space_reports_the_volume_under_a_path_that_does_not_exist_yet(tmp_path):
    """The precheck runs before the folder exists, so it walks up to one that does."""
    assert album._free_space(tmp_path / "not" / "there" / "yet") > 0


def test_require_tools_is_satisfied_when_both_are_present(monkeypatch):
    """Both tools must actually be looked for; an empty body would pass otherwise."""
    asked = []
    monkeypatch.setattr(
        "fototrip.album.shutil.which", lambda name: asked.append(name) or f"/usr/bin/{name}"
    )
    require_tools()  # does not raise
    assert asked == ["osxphotos", "exiftool"]


def test_a_missing_osxphotos_names_the_extra_to_install(monkeypatch):
    monkeypatch.setattr(
        "fototrip.album.shutil.which", lambda name: None if name == "osxphotos" else "/usr/bin/x"
    )
    with pytest.raises(ExportRefused) as excinfo:
        require_tools()
    assert "osxphotos" in excinfo.value.message
    assert ".[album]" in excinfo.value.message


def test_a_missing_exiftool_names_how_to_install_it(monkeypatch):
    monkeypatch.setattr(
        "fototrip.album.shutil.which", lambda name: None if name == "exiftool" else "/usr/bin/x"
    )
    with pytest.raises(ExportRefused) as excinfo:
        require_tools()
    assert "exiftool" in excinfo.value.message
    assert "brew" in excinfo.value.message


def test_osxphotos_is_looked_for_beside_the_running_interpreter_first(tmp_path, monkeypatch):
    """`pip install -e '.[album]'` puts it in fototrip's own venv, not on PATH.

    Running `<venv>/bin/fototrip` does not add `<venv>/bin` to PATH, so a bare
    "osxphotos" is not found even though the documented install put it there.
    """
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "osxphotos").write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "executable", str(bin_dir / "python3"))

    assert album._default_osxphotos() == str(bin_dir / "osxphotos")


def test_osxphotos_falls_back_to_the_bare_name_when_not_beside_the_interpreter(
    tmp_path, monkeypatch
):
    """A Homebrew or system install is still found the ordinary way, via PATH."""
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(bin_dir / "python3"))

    assert album._default_osxphotos() == "osxphotos"


def test_a_custom_osxphotos_path_is_the_one_checked(monkeypatch):
    seen = []
    monkeypatch.setattr(
        "fototrip.album.shutil.which", lambda name: seen.append(name) or "/usr/bin/x"
    )
    require_tools(osxphotos="/opt/homebrew/bin/osxphotos")
    assert "/opt/homebrew/bin/osxphotos" in seen


def test_run_osxphotos_returns_the_exit_status_of_the_command():
    """A non-zero status comes back as a value, not as an exception.

    export_album reads this return value and raises ExportRefused itself, so a
    runner that raised CalledProcessError would bypass its refusal path.
    """
    assert run_osxphotos([sys.executable, "-c", "raise SystemExit(3)"]) == 3


def test_run_osxphotos_returns_zero_for_a_command_that_succeeds():
    assert run_osxphotos([sys.executable, "-c", ""]) == 0
