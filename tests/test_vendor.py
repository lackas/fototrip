import hashlib
import json
from pathlib import Path

import pytest

VENDOR = Path(__file__).resolve().parent.parent / "src" / "fototrip" / "assets" / "vendor"


def _lock():
    return json.loads((VENDOR / "VENDOR.lock.json").read_text())


def test_every_locked_file_exists_and_matches_its_hash():
    for rel, meta in _lock().items():
        path = VENDOR / rel
        assert path.exists(), f"{rel} missing — run tools/vendor_assets.py"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == meta["sha256"], rel


def test_no_unlocked_files_in_vendor_tree():
    # Walk VENDOR_DIR and collect all files (excluding VENDOR.lock.json itself)
    physical_files = set()
    for path in VENDOR.rglob("*"):
        if path.is_file() and path.name != "VENDOR.lock.json":
            # Convert to relative path with forward slashes to match lockfile key format
            rel_path = path.relative_to(VENDOR).as_posix()
            physical_files.add(rel_path)

    # Get all keys from the lockfile
    locked_files = set(_lock().keys())

    # Physical files and locked files must be exactly equal
    assert physical_files == locked_files


@pytest.mark.parametrize(
    "rel",
    [
        "leaflet/leaflet.js",
        "leaflet/leaflet.css",
        "markercluster/markercluster.js",
        "photoswipe/photoswipe.esm.js",
        "photoswipe/photoswipe.css",
    ],
)
def test_required_libraries_are_present(rel):
    assert (VENDOR / rel).stat().st_size > 1000
