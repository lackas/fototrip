"""Assemble the single JSON payload the frontend loads."""

import re
from collections import Counter
from pathlib import Path

from fototrip.images import Derivatives
from fototrip.models import Photo

_COORD_PRECISION = 6

# photo_id becomes both a JSON field the frontend puts into the DOM (thumb/web
# URLs) and a real filename on disk, so it is restricted to a plainly safe
# character set. Anything else -- quotes, '#', spaces, path separators -- is
# replaced before the uniqueness loop runs, so two different names that
# sanitise to the same string still can't collide.
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def assign_ids(photos: list[Photo]) -> list[Photo]:
    """Give each photo a filesystem- and markup-safe id, unique within the trip.

    Ids are filename stems because they are recognisable, but two subfolders can
    hold the same stem, so later duplicates get a numeric suffix.
    """
    # Sort by source path for stable ordering regardless of input order
    sorted_photos = sorted(photos, key=lambda p: str(p.source))

    used_ids = set()
    result = []
    for photo in sorted_photos:
        stem = _UNSAFE_CHARS.sub("_", Path(photo.source).stem) or "photo"

        # Find the next available id with this stem, bumping counter until unused
        counter = 1
        while True:
            if counter == 1:
                candidate_id = stem
            else:
                candidate_id = f"{stem}-{counter}"

            if candidate_id not in used_ids:
                used_ids.add(candidate_id)
                result.append(photo.evolve(photo_id=candidate_id))
                break

            counter += 1

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
