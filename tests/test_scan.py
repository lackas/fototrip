from pathlib import Path

from fototrip.scan import find_photos


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


def test_finds_jpegs_recursively_and_sorted(tmp_path):
    _touch(tmp_path / "b.jpeg")
    _touch(tmp_path / "a.jpg")
    _touch(tmp_path / "sub" / "c.JPEG")
    assert [p.name for p in find_photos(tmp_path)] == ["a.jpg", "b.jpeg", "c.JPEG"]


def test_excludes_video_and_non_images(tmp_path):
    _touch(tmp_path / "keep.jpeg")
    for name in ("clip.mov", "clip.mp4", "notes.txt", "trip.toml"):
        _touch(tmp_path / name)
    assert [p.name for p in find_photos(tmp_path)] == ["keep.jpeg"]


def test_excludes_hidden_and_appledouble_files(tmp_path):
    _touch(tmp_path / "keep.jpeg")
    _touch(tmp_path / ".hidden.jpeg")
    _touch(tmp_path / "._keep.jpeg")
    _touch(tmp_path / ".git" / "buried.jpeg")
    assert [p.name for p in find_photos(tmp_path)] == ["keep.jpeg"]


def test_includes_heic(tmp_path):
    _touch(tmp_path / "IMG_1.heic")
    assert [p.name for p in find_photos(tmp_path)] == ["IMG_1.heic"]
