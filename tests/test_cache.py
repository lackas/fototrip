from fototrip.cache import BuildCache


def _src(tmp_path, content=b"aaaa"):
    p = tmp_path / "IMG_1.jpeg"
    p.write_bytes(content)
    return p


def _out(tmp_path, name="thumb.jpg"):
    p = tmp_path / name
    p.write_bytes(b"out")
    return p


def test_unrecorded_source_is_not_fresh(tmp_path):
    cache = BuildCache(tmp_path / "cache.json")
    assert cache.is_fresh(_src(tmp_path), [_out(tmp_path)]) is False


def test_recorded_unchanged_source_is_fresh(tmp_path):
    cache = BuildCache(tmp_path / "cache.json")
    src, out = _src(tmp_path), _out(tmp_path)
    cache.record(src)
    assert cache.is_fresh(src, [out]) is True


def test_changed_size_is_not_fresh(tmp_path):
    """A file truncated mid-export gets reprocessed once the export completes."""
    cache = BuildCache(tmp_path / "cache.json")
    src, out = _src(tmp_path, b"aa"), _out(tmp_path)
    cache.record(src)
    src.write_bytes(b"aaaaaaaa")
    assert cache.is_fresh(src, [out]) is False


def test_changed_mtime_is_not_fresh(tmp_path):
    import os

    cache = BuildCache(tmp_path / "cache.json")
    src, out = _src(tmp_path), _out(tmp_path)
    cache.record(src)
    os.utime(src, (0, 0))
    assert cache.is_fresh(src, [out]) is False


def test_missing_output_is_not_fresh(tmp_path):
    """Deleting the site folder must force a rebuild even with a warm cache."""
    cache = BuildCache(tmp_path / "cache.json")
    src, out = _src(tmp_path), _out(tmp_path)
    cache.record(src)
    out.unlink()
    assert cache.is_fresh(src, [out]) is False


def test_cache_survives_a_round_trip(tmp_path):
    path = tmp_path / "cache.json"
    src, out = _src(tmp_path), _out(tmp_path)
    first = BuildCache(path)
    first.record(src)
    first.save()
    assert BuildCache(path).is_fresh(src, [out]) is True


def test_corrupt_cache_file_is_ignored(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{not json")
    cache = BuildCache(path)
    assert cache.is_fresh(_src(tmp_path), [_out(tmp_path)]) is False


def test_stats_count_hits_and_misses(tmp_path):
    cache = BuildCache(tmp_path / "cache.json")
    src, out = _src(tmp_path), _out(tmp_path)
    cache.is_fresh(src, [out])
    cache.record(src)
    cache.is_fresh(src, [out])
    assert (cache.stats.hits, cache.stats.misses) == (1, 1)
