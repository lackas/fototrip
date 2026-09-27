import json

from fototrip.cache import BuildCache


def _cache(tmp_path, path=None, **overrides):
    overrides.setdefault("root", tmp_path)
    overrides.setdefault("thumb_px", 96)
    overrides.setdefault("web_px", 1600)
    return BuildCache(path or tmp_path / "cache.json", **overrides)


def _src(tmp_path, content=b"aaaa", name="IMG_1.jpeg"):
    p = tmp_path / name
    p.write_bytes(content)
    return p


def _out(tmp_path, name="thumb.jpg"):
    p = tmp_path / name
    p.write_bytes(b"out")
    return p


def test_unrecorded_source_is_not_fresh(tmp_path):
    cache = _cache(tmp_path)
    assert cache.is_fresh(_src(tmp_path), [_out(tmp_path)]) is False


def test_recorded_unchanged_source_is_fresh(tmp_path):
    cache = _cache(tmp_path)
    src, out = _src(tmp_path), _out(tmp_path)
    cache.record(src)
    assert cache.is_fresh(src, [out]) is True


def test_changed_size_is_not_fresh(tmp_path):
    """A file truncated mid-export gets reprocessed once the export completes."""
    cache = _cache(tmp_path)
    src, out = _src(tmp_path, b"aa"), _out(tmp_path)
    cache.record(src)
    src.write_bytes(b"aaaaaaaa")
    assert cache.is_fresh(src, [out]) is False


def test_changed_mtime_is_not_fresh(tmp_path):
    import os

    cache = _cache(tmp_path)
    src, out = _src(tmp_path), _out(tmp_path)
    cache.record(src)
    os.utime(src, (0, 0))
    assert cache.is_fresh(src, [out]) is False


def test_missing_output_is_not_fresh(tmp_path):
    """Deleting the site folder must force a rebuild even with a warm cache."""
    cache = _cache(tmp_path)
    src, out = _src(tmp_path), _out(tmp_path)
    cache.record(src)
    out.unlink()
    assert cache.is_fresh(src, [out]) is False


def test_cache_survives_a_round_trip(tmp_path):
    path = tmp_path / "cache.json"
    src, out = _src(tmp_path), _out(tmp_path)
    first = _cache(tmp_path, path)
    first.record(src)
    first.save()
    assert _cache(tmp_path, path).is_fresh(src, [out]) is True


def test_corrupt_cache_file_is_ignored(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{not json")
    cache = _cache(tmp_path, path)
    assert cache.is_fresh(_src(tmp_path), [_out(tmp_path)]) is False


def test_stats_count_hits_and_misses(tmp_path):
    cache = _cache(tmp_path)
    src, out = _src(tmp_path), _out(tmp_path)
    cache.is_fresh(src, [out])
    cache.record(src)
    cache.is_fresh(src, [out])
    assert (cache.stats.hits, cache.stats.misses) == (1, 1)


def test_cache_key_is_relative_to_root_not_absolute(tmp_path):
    """The cache file is published inside the site, so its keys must never
    carry the machine's absolute path -- that would leak the home directory
    and the trip folder's layout."""
    path = tmp_path / "cache.json"
    src = _src(tmp_path)
    cache = _cache(tmp_path, path)
    cache.record(src)
    cache.save()

    raw = json.loads(path.read_text())
    assert list(raw.keys()) == ["IMG_1.jpeg"]
    assert str(tmp_path) not in next(iter(raw.keys()))


def test_a_source_in_a_subfolder_gets_a_relative_key(tmp_path):
    path = tmp_path / "cache.json"
    (tmp_path / "sub").mkdir()
    src = _src(tmp_path, name="sub/IMG_1.jpeg")
    cache = _cache(tmp_path, path)
    cache.record(src)
    cache.save()

    raw = json.loads(path.read_text())
    assert list(raw.keys()) == ["sub/IMG_1.jpeg"]


def test_root_given_resolved_or_not_produces_the_same_key(tmp_path):
    """`root` is resolved internally, so whether the caller already resolved
    it (as an absolute CLI folder argument would be) or not makes no
    difference -- this is what lets a relative and an absolute invocation of
    the same trip share cache hits (covered end to end in test_cli.py)."""
    path = tmp_path / "cache.json"
    src = _src(tmp_path)

    unresolved_root = _cache(tmp_path, path, root=tmp_path)
    unresolved_root.record(src)
    unresolved_root.save()

    resolved_root = _cache(tmp_path, path, root=tmp_path.resolve())
    assert resolved_root.is_fresh(src, [_out(tmp_path)]) is True


def test_changed_thumb_px_is_not_fresh(tmp_path):
    """--thumb-px changes the derivative, so it must be part of the cache key."""
    src, out = _src(tmp_path), _out(tmp_path)
    original = _cache(tmp_path, thumb_px=96)
    original.record(src)

    resized = _cache(tmp_path, thumb_px=128)
    assert resized.is_fresh(src, [out]) is False


def test_changed_web_px_is_not_fresh(tmp_path):
    """--web-px changes the derivative, so it must be part of the cache key."""
    src, out = _src(tmp_path), _out(tmp_path)
    original = _cache(tmp_path, web_px=1600)
    original.record(src)

    resized = _cache(tmp_path, web_px=800)
    assert resized.is_fresh(src, [out]) is False
