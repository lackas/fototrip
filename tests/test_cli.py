import json
from datetime import datetime
from pathlib import Path

from click.testing import CliRunner
from PIL import Image

from fototrip import cli
from fototrip.cli import main
from fototrip.models import Photo
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


def test_every_derivative_failing_exits_nonzero_with_a_clear_message(
    make_jpeg, tmp_path, monkeypatch
):
    """The comment justifying _derive_one's broad `except Exception` promises
    that a systematic failure "exits non-zero if nothing could be included."
    Nothing enforced that: every photo passing metadata but every derivative
    failing left `entries` empty, and the build wrote an empty site and
    exited 0. Corrupting every source right before the derivative stage (in
    the parent process, like the single-victim test above) makes every
    worker's real, unpatched `build_derivatives` call fail for a genuine
    reason."""
    trip = make_jpeg("IMG_1.jpeg").parent
    make_jpeg("IMG_2.jpeg", lat=IGUAZU[0], lon=IGUAZU[1])
    out = tmp_path / "site"

    real_assign_ids = cli.assign_ids

    def _assign_ids_then_corrupt_every_source(photos):
        assigned = real_assign_ids(photos)
        for photo in assigned:
            photo.source.write_bytes(b"not a jpeg")
        return assigned

    monkeypatch.setattr(cli, "assign_ids", _assign_ids_then_corrupt_every_source)

    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])

    assert result.exit_code != 0
    assert "no photos could be included" in result.output.lower()
    assert "0 photos included" in result.output
    assert not (out / "photos.json").exists()


def test_relative_and_absolute_folder_paths_share_cache_hits(make_jpeg, tmp_path, monkeypatch):
    """The cache used to key on the folder argument exactly as given, so
    building the same trip once with a relative path and once with an
    absolute one looked like two different trips and re-encoded everything."""
    trip = make_jpeg("IMG_1.jpeg").parent
    out = tmp_path / "site"

    first = CliRunner().invoke(main, ["build", str(trip.resolve()), "-o", str(out)])
    assert first.exit_code == 0, first.output

    monkeypatch.chdir(trip.parent)
    relative = trip.relative_to(trip.parent)
    second = CliRunner().invoke(main, ["build", str(relative), "-o", str(out)])

    assert second.exit_code == 0, second.output
    assert "1 cached" in second.output


def test_an_interrupted_derivative_stage_still_saves_completed_records(
    make_jpeg, tmp_path, monkeypatch
):
    """Ctrl-C during the derivative pool must not discard cache records for
    derivatives that already finished and are sitting on disk -- otherwise a
    full-size re-export interrupted near the end restarts from zero instead
    of resuming.

    Faking `ProcessPoolExecutor` runs this entirely in-process, with none of
    the spawn-boundary tricks other tests in this file need: `cli._derive_one`
    is real and unpatched, so the one derivative that completes before the
    simulated interrupt is a genuine result written by genuine code, not a
    stand-in for it.
    """
    trip = make_jpeg("IMG_1.jpeg").parent
    make_jpeg("IMG_2.jpeg", lat=IGUAZU[0], lon=IGUAZU[1])
    out = tmp_path / "site"

    class _PoolInterruptsAfterOne:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def map(self, func, iterable, chunksize=1):
            items = list(iterable)
            yield func(items[0])
            raise KeyboardInterrupt("simulated ctrl-c")

    monkeypatch.setattr(cli, "ProcessPoolExecutor", lambda *a, **k: _PoolInterruptsAfterOne())

    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])

    assert result.exit_code != 0

    cache_path = out / cli.CACHE_FILENAME
    assert cache_path.exists(), "the interrupted build must still have saved a cache file"
    saved = json.loads(cache_path.read_text())
    assert len(saved) == 1, "exactly the one derivative that finished before the interrupt"
    assert len(list((out / "thumb").glob("*.jpg"))) == 1
    assert len(list((out / "web").glob("*.jpg"))) == 1


def test_changing_thumb_px_invalidates_the_whole_cache_entry(make_jpeg, tmp_path):
    """A warm re-run with a different --thumb-px must not report the old-sized
    thumbnail as cached -- the size is part of what makes a derivative
    "current". thumb_px and web_px share one signature (a deliberately
    simple, coarser rule, not a per-derivative one), so this rebuilds *both*
    derivatives, not just the thumbnail whose size actually changed."""
    trip = make_jpeg("IMG_1.jpeg").parent
    out = tmp_path / "site"
    CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])
    web_before = (out / "web" / "IMG_1.jpg").stat().st_mtime_ns

    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out), "--thumb-px", "128"])

    assert result.exit_code == 0, result.output
    assert "1 written" in result.output
    assert Image.open(out / "thumb" / "IMG_1.jpg").size == (128, 128)
    # The web derivative's size is unaffected by --thumb-px, but it was
    # rewritten anyway: proof the whole entry was invalidated, not just the
    # thumbnail.
    assert (out / "web" / "IMG_1.jpg").stat().st_mtime_ns != web_before


def test_title_flag_overrides_the_folder_name(make_jpeg, tmp_path):
    trip = make_jpeg("IMG_1.jpeg").parent
    out = tmp_path / "site"
    CliRunner().invoke(main, ["build", str(trip), "-o", str(out), "--title", "Argentina 2026"])
    assert "<title>Argentina 2026</title>" in (out / "index.html").read_text()


def test_one_photo_failing_during_derivative_generation_does_not_crash_the_build(
    make_jpeg, tmp_path, monkeypatch
):
    """A file that goes away between the metadata scan and the derivative stage
    (Photos still writing the export, a permission hiccup, ...) must be skipped,
    not crash the whole pool.

    `ProcessPoolExecutor` uses the 'spawn' start method here, so a worker
    process re-imports `fototrip.cli` fresh: monkeypatching
    `fototrip.cli.build_derivatives` in this process does not reach it (verified
    separately). Deleting the victim's source file inside a patched
    `assign_ids` -- which runs in the parent, before the pool starts -- creates
    a real, physical failure that the unpatched worker genuinely hits.
    """
    trip = make_jpeg("good.jpeg").parent
    victim = make_jpeg("victim.jpeg", lat=IGUAZU[0], lon=IGUAZU[1])
    out = tmp_path / "site"

    real_assign_ids = cli.assign_ids

    def _assign_ids_then_delete_victim(photos):
        assigned = real_assign_ids(photos)
        victim.unlink()
        return assigned

    monkeypatch.setattr(cli, "assign_ids", _assign_ids_then_delete_victim)

    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])

    assert result.exit_code == 0, result.output
    assert "unreadable or truncated image" in result.output
    manifest = json.loads((out / "photos.json").read_text())
    assert len(manifest["photos"]) == 1
    assert manifest["photos"][0]["id"] == "good"

    # No cache.record() for the failure means a later run retries it. Undo the
    # patch first: it would delete the recreated file all over again otherwise.
    monkeypatch.undo()
    make_jpeg("victim.jpeg", lat=IGUAZU[0], lon=IGUAZU[1])
    second = CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])
    assert second.exit_code == 0, second.output
    assert len(json.loads((out / "photos.json").read_text())["photos"]) == 2


def test_a_corrupted_cached_derivative_is_rebuilt_not_fatal(make_jpeg, tmp_path):
    """BuildCache.is_fresh only checks that the output file exists, never that
    it is readable. A derivative truncated or clobbered out-of-band while the
    cache still calls it fresh must trigger a rebuild, not a crash."""
    trip = make_jpeg("IMG_1.jpeg").parent
    out = tmp_path / "site"
    CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])

    web = out / "web" / "IMG_1.jpg"
    web.write_bytes(b"not a jpeg")  # corrupt the derivative, cache file untouched

    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])

    assert result.exit_code == 0, result.output
    manifest = json.loads((out / "photos.json").read_text())
    assert len(manifest["photos"]) == 1
    with Image.open(web) as image:
        image.load()  # rebuilt into a valid JPEG, not left corrupted


def test_warm_build_does_not_rewrite_unchanged_derivatives(make_jpeg, tmp_path):
    """The spec requires that re-running the build only processes new files.
    JPEG encoding here is deterministic, so a redundant rewrite is
    byte-identical -- mtime is the only signal that separates "skipped" from
    "recomputed"."""
    trip = make_jpeg("IMG_1.jpeg").parent
    out = tmp_path / "site"
    CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])

    thumb = out / "thumb" / "IMG_1.jpg"
    web = out / "web" / "IMG_1.jpg"
    thumb_before = thumb.stat().st_mtime_ns
    web_before = web.stat().st_mtime_ns

    make_jpeg("IMG_2.jpeg", lat=BUENOS_AIRES[0], lon=BUENOS_AIRES[1])
    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])

    assert result.exit_code == 0, result.output
    assert thumb.stat().st_mtime_ns == thumb_before
    assert web.stat().st_mtime_ns == web_before
    assert (out / "thumb" / "IMG_2.jpg").exists()
    assert (out / "web" / "IMG_2.jpg").exists()


def test_derive_one_catches_a_non_oserror_failure_from_build_derivatives(monkeypatch, tmp_path):
    """`Image.DecompressionBombError` does not subclass `OSError`, so round 1's
    narrower tuple would have let it crash the worker. This calls `_derive_one`
    directly, in this process, rather than through a real `ProcessPoolExecutor`.

    That is a deliberate, disclosed gap: a monkeypatch of `build_derivatives`
    cannot reach a spawned worker (round 1's report), and staging a real
    cross-process `DecompressionBombError` would require an oversized image --
    but the bomb check fires in `Image.open()` on file size alone, so such an
    image would also blow up `fototrip.metadata.read_photo`'s own unrelated
    `Image.open()` call during the metadata scan, before ever reaching the
    worker, and `metadata.py` is out of this task's scope to touch. Exception
    handling is identical regardless of which process runs it, so this still
    proves the exact try/except logic the worker executes; it just does not
    additionally prove that a `DecompressionBombError` pickles cleanly across
    the process boundary (it never has to -- `_derive_one` catches it locally
    and only the `(photo, None)` marker crosses, which the pool already carries
    correctly for other failures per the round-1 test).
    """
    photo = Photo(
        source=tmp_path / "whatever.jpeg",
        lat=0.0,
        lon=0.0,
        naive_dt=datetime(2026, 7, 17, 19, 37, 59),  # noqa: DTZ001 -- Photo.naive_dt is tz-naive by design
        utc_offset=None,
        width=1,
        height=1,
        camera=None,
        photo_id="whatever",
    )

    def _bomb(*args, **kwargs):
        raise Image.DecompressionBombError("staged for test")

    monkeypatch.setattr(cli, "build_derivatives", _bomb)

    result_photo, derivatives = cli._derive_one(photo, out_dir=tmp_path, thumb_px=96, web_px=1600)

    assert result_photo is photo
    assert derivatives is None


def test_a_non_oserror_failure_in_the_warm_cache_read_triggers_a_rebuild(
    make_jpeg, tmp_path, monkeypatch
):
    """Mirrors the previous test for the *other* widened catch: the warm-cache
    dimension read. Unlike the worker, this loop runs in the parent process (only
    stale photos go through the pool), so a direct monkeypatch of `Image.open`
    genuinely exercises the real, production code path end to end through the
    CLI -- no disclosed gap here.

    The trip and output folders are kept as siblings (not nested, unlike most of
    this file's other tests) specifically so the second build's metadata scan
    never re-opens `web/IMG_1.jpg` itself: that would hit the same patched
    `Image.open` and crash `read_photo` (out of scope) before the build ever
    reached the warm-cache read this test targets.
    """
    trip = make_jpeg("IMG_1.jpeg", subdir="trip").parent
    out = tmp_path / "site"
    CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])

    web = out / "web" / "IMG_1.jpg"
    real_open = Image.open

    def _bomb_on_the_cached_derivative(fp, *args, **kwargs):
        if Path(fp) == web:
            raise Image.DecompressionBombError("staged for test")
        return real_open(fp, *args, **kwargs)

    monkeypatch.setattr(Image, "open", _bomb_on_the_cached_derivative)

    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])

    assert result.exit_code == 0, result.output
    manifest = json.loads((out / "photos.json").read_text())
    assert len(manifest["photos"]) == 1
    assert manifest["photos"][0]["id"] == "IMG_1"
