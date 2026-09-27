"""Assemble the single JSON payload the frontend loads."""

from collections import Counter
from pathlib import Path

from fototrip.images import Derivatives
from fototrip.models import Photo

_COORD_PRECISION = 6


def assign_ids(photos: list[Photo]) -> list[Photo]:
    """Give each photo a filesystem-safe id, unique within the trip.

    Ids are filename stems because they are recognisable, but two subfolders can
    hold the same stem, so later duplicates get a numeric suffix.
    """
    seen: Counter[str] = Counter()
    result = []
    for photo in photos:
        stem = Path(photo.source).stem
        seen[stem] += 1
        suffix = "" if seen[stem] == 1 else f"-{seen[stem]}"
        result.append(photo.evolve(photo_id=f"{stem}{suffix}"))
    return result


def build_manifest(entries: list[tuple[Photo, Derivatives]]) -> dict:
    """Build the photos.json payload, ordered by local capture time."""
    ordered = sorted(entries, key=lambda pair: (pair[0].local_dt, pair[0].photo_id))

    photos = [
        {
            "id": photo.photo_id,
            "thumb": derivatives.thumb_rel,
            "web": derivatives.web_rel,
            "w": derivatives.web_width,
            "h": derivatives.web_height,
            "lat": round(photo.lat, _COORD_PRECISION),
            "lon": round(photo.lon, _COORD_PRECISION),
            "t": photo.local_dt.isoformat(),
            "day": photo.day,
            "camera": photo.camera,
        }
        for photo, derivatives in ordered
    ]

    day_counts = Counter(entry["day"] for entry in photos)
    days = [{"day": day, "count": day_counts[day]} for day in sorted(day_counts)]

    bounds = None
    if photos:
        lats = [entry["lat"] for entry in photos]
        lons = [entry["lon"] for entry in photos]
        bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]

    return {"photos": photos, "days": days, "bounds": bounds}
