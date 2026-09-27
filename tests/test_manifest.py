from datetime import datetime, timedelta
from pathlib import Path

from fototrip.images import Derivatives
from fototrip.manifest import assign_ids, build_manifest
from fototrip.models import Photo


def _photo(name, day, hour, lat=-25.6, lon=-54.4, subdir=""):
    local = datetime.fromisoformat(f"{day}T{hour:02d}:00:00-03:00")
    return Photo(
        source=Path(subdir) / name,
        lat=lat,
        lon=lon,
        naive_dt=local.replace(tzinfo=None),
        utc_offset=timedelta(hours=2),
        width=480,
        height=640,
        camera="iPhone 17 Pro",
        local_dt=local,
        day=day,
    )


def _derivs(photo_id):
    return Derivatives(f"thumb/{photo_id}.jpg", f"web/{photo_id}.jpg", 480, 640)


def test_ids_come_from_the_filename_stem():
    [photo] = assign_ids([_photo("IMG_4656.jpeg", "2026-07-17", 19)])
    assert photo.photo_id == "IMG_4656"


def test_colliding_stems_get_distinct_ids():
    """Two subfolders can each hold an IMG_0001.jpeg; derivatives must not collide."""
    photos = assign_ids(
        [
            _photo("IMG_0001.jpeg", "2026-07-17", 9, subdir="a"),
            _photo("IMG_0001.jpeg", "2026-07-17", 10, subdir="b"),
            _photo("IMG_0001.jpeg", "2026-07-17", 11, subdir="c"),
        ]
    )
    ids = [p.photo_id for p in photos]
    assert ids == ["IMG_0001", "IMG_0001-2", "IMG_0001-3"]
    assert len(set(ids)) == 3


def test_manifest_is_ordered_by_local_time():
    photos = assign_ids(
        [
            _photo("late.jpeg", "2026-07-19", 18),
            _photo("early.jpeg", "2026-07-17", 8),
            _photo("middle.jpeg", "2026-07-18", 12),
        ]
    )
    result = build_manifest([(p, _derivs(p.photo_id)) for p in photos])
    assert [entry["id"] for entry in result["photos"]] == ["early", "middle", "late"]


def test_manifest_entry_shape():
    [photo] = assign_ids([_photo("IMG_1.jpeg", "2026-07-19", 10)])
    result = build_manifest([(photo, _derivs("IMG_1"))])
    entry = result["photos"][0]
    assert entry == {
        "id": "IMG_1",
        "thumb": "thumb/IMG_1.jpg",
        "web": "web/IMG_1.jpg",
        "w": 480,
        "h": 640,
        "lat": -25.6,
        "lon": -54.4,
        "t": "2026-07-19T10:00:00-03:00",
        "day": "2026-07-19",
        "camera": "iPhone 17 Pro",
    }


def test_days_summary_counts_photos_in_order():
    photos = assign_ids(
        [
            _photo("a.jpeg", "2026-07-17", 9),
            _photo("b.jpeg", "2026-07-19", 9),
            _photo("c.jpeg", "2026-07-19", 10),
        ]
    )
    result = build_manifest([(p, _derivs(p.photo_id)) for p in photos])
    assert result["days"] == [
        {"day": "2026-07-17", "count": 1},
        {"day": "2026-07-19", "count": 2},
    ]


def test_bounds_span_all_photos():
    photos = assign_ids(
        [
            _photo("home.jpeg", "2026-07-17", 19, lat=50.93, lon=6.96),
            _photo("ar.jpeg", "2026-07-19", 10, lat=-25.68, lon=-54.44),
        ]
    )
    result = build_manifest([(p, _derivs(p.photo_id)) for p in photos])
    assert result["bounds"] == [[-25.68, -54.44], [50.93, 6.96]]


def test_coordinates_are_rounded_to_six_decimals():
    """Six decimals is ~0.1 m; more is noise that only inflates the JSON."""
    [photo] = assign_ids([_photo("a.jpeg", "2026-07-19", 10, lat=-25.68581666666667)])
    result = build_manifest([(photo, _derivs("a"))])
    assert result["photos"][0]["lat"] == -25.685817


def test_empty_input_yields_an_empty_manifest_not_a_crash():
    result = build_manifest([])
    assert result["photos"] == []
    assert result["days"] == []
    assert result["bounds"] is None
