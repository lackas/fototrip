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


def _assert_no_unsafe_keys(raw: dict) -> None:
    for key in raw:
        assert not key.startswith("/"), f"key {key!r} is an absolute path"
        assert ".." not in key.split("/"), f"key {key!r} contains a '..' segment"


def test_stale_absolute_keys_from_a_pre_fix_cache_file_are_dropped_on_load(tmp_path):
    """An older version of this class keyed entries on the absolute source
    path. Loading one of those files and writing it straight back out would
    keep publishing the leak this class exists to close, forever. The
    tainted entry must be dropped, not carried forward."""
    path = tmp_path / "cache.json"
    leaked_absolute_key = str(tmp_path / "IMG_1.jpeg")
    path.write_text(json.dumps({leaked_absolute_key: [897, 123.0, 96, 1600]}))

    cache = _cache(tmp_path, path)
    assert cache.is_fresh(_src(tmp_path), [_out(tmp_path)]) is False

    cache.save()
    raw = json.loads(path.read_text())
    assert leaked_absolute_key not in raw
    _assert_no_unsafe_keys(raw)


def test_keys_with_dotdot_segments_are_dropped_on_load(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"../../etc/passwd": [1, 2.0, 96, 1600]}))

    cache = _cache(tmp_path, path)
    cache.save()

    raw = json.loads(path.read_text())
    _assert_no_unsafe_keys(raw)
    assert raw == {}


def test_a_source_symlinked_in_from_outside_root_gets_a_hashed_key_not_its_path(tmp_path):
    """Photos living on another volume and symlinked into the trip folder is
    an ordinary setup. `_key()`'s fallback for a source that `relative_to`
    can't place under `root` must not become the absolute path itself --
    that would leak exactly like the original bug, just through a side
    door."""
    outside = tmp_path / "outside"
    outside.mkdir()
    real_source = _src(outside)

    root = tmp_path / "trip"
    root.mkdir()
    symlink = root / "IMG_1.jpeg"
    symlink.symlink_to(real_source)

    path = tmp_path / "cache.json"
    cache = _cache(tmp_path, path, root=root)
    cache.record(symlink)
    cache.save()

    raw = json.loads(path.read_text())
    _assert_no_unsafe_keys(raw)
    assert str(real_source) not in json.dumps(raw)
    assert str(outside) not in json.dumps(raw)

    # Stable across a fresh instance, so the symlinked source stays cacheable.
    reloaded = _cache(tmp_path, path, root=root)
    assert reloaded.is_fresh(symlink, [_out(tmp_path)]) is True
