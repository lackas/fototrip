"""Find candidate photo files in a trip folder."""

from pathlib import Path

PHOTO_SUFFIXES = frozenset({".jpg", ".jpeg", ".heic", ".heif", ".png"})


def find_photos(root: Path) -> list[Path]:
    """Return every candidate photo under `root`, sorted by name.

    Hidden files, AppleDouble sidecars and anything inside a dot-directory are
    excluded: they carry image extensions but no image data.
    """
    found = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in PHOTO_SUFFIXES:
            continue
        if path.name.startswith(".") or path.name.startswith("._"):
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts[:-1]):
            continue
        found.append(path)
    return sorted(found, key=lambda p: p.name)
