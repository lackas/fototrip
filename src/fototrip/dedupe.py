"""Drop photos that are the same shot twice.

Re-adding pictures to an iCloud Shared Album creates fresh assets, so an
export hands out the same frame under two names -- `IMG_1670.jpg` and
`IMG_1670 (1).jpg`. One real album carried 95 such pairs among ~2500 photos.
They are not a storage problem: each one becomes a second pin on the map at
the same second and the same spot, which is precisely what this site exists to
show you.

Timestamp and position alone are not enough to call two photos the same. The
same album held 34 pictures that shared both and were genuinely different
photographs -- a burst, or two people shooting at once. So the content decides,
and only for photos that already agree on when and where, which keeps the cost
to the handful of files that actually collide rather than the whole trip.
"""

from collections import defaultdict

from PIL import Image

from fototrip.models import Photo

# A 16x16 average hash: identical enough to survive two JPEG encodings of one
# frame, different enough that two pictures of the same scene do not collide.
# Used only inside a group that already agrees on capture second and position,
# so it never has to tell apart photos taken anywhere else or at another time.
_HASH_SIDE = 16


def _content_hash(photo: Photo) -> int | None:
    """A perceptual hash of the image, or None if it cannot be read.

    None means "do not judge this one": an unreadable file is kept rather than
    dropped, because a photo that vanishes from a build with no line in the
    report explaining it is worse than a duplicate that stays.
    """
    try:
        with Image.open(photo.source) as image:
            small = image.convert("L").resize((_HASH_SIDE, _HASH_SIDE), Image.BILINEAR)
        # tobytes() rather than getdata(): one byte per pixel for mode "L", and
        # getdata() is deprecated for removal in Pillow 14.
        pixels = small.tobytes()
    except Exception:  # noqa: BLE001 -- deliberately broad, see below
        # Truncated, clobbered, a decompression bomb, an unsupported mode: all
        # of them mean the same thing here, and enumerating them would only
        # invite the one that was not on the list to drop a real photo.
        return None
    average = sum(pixels) / len(pixels)
    return sum(1 << i for i, value in enumerate(pixels) if value > average)


def _keeper(photos: list[Photo]) -> Photo:
    """Of several copies of one frame, the one carrying most of it.

    A shared-album copy is usually a smaller re-encode of the same picture, so
    the larger file is the better one to publish. Ties fall back to the shorter
    name and then alphabetically, which keeps `IMG_1670.jpg` ahead of
    `IMG_1670 (1).jpg` and makes the choice reproducible.
    """
    return min(photos, key=lambda p: (-p.source.stat().st_size, len(p.source.name), p.source.name))


def drop_duplicates(photos: list[Photo]) -> tuple[list[Photo], int]:
    """Return the photos worth publishing, and how many copies were dropped.

    Input order is preserved: later stages assign ids and build the manifest
    from this list, and a reshuffle there would change every photo's id.
    """
    groups: dict[tuple, list[Photo]] = defaultdict(list)
    for photo in photos:
        groups[(photo.local_dt, photo.lat, photo.lon)].append(photo)

    dropped: set[int] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        by_content: dict[int, list[Photo]] = defaultdict(list)
        for photo in group:
            digest = _content_hash(photo)
            if digest is not None:
                by_content[digest].append(photo)
        for same in by_content.values():
            if len(same) < 2:
                continue
            keep = _keeper(same)
            dropped.update(id(p) for p in same if p is not keep)

    kept = [p for p in photos if id(p) not in dropped]
    return kept, len(dropped)
