"""Read one photo's EXIF into a Photo record."""

from datetime import datetime, timedelta
from pathlib import Path

from PIL import ExifTags, Image, UnidentifiedImageError

from fototrip.models import Photo, SkipPhoto, SkipReason

_DATETIME_ORIGINAL = 0x9003
_OFFSET_TIME_ORIGINAL = 0x9011
_MODEL = 0x0110
_ORIENTATION = 0x0112
_GPS_LAT_REF, _GPS_LAT, _GPS_LON_REF, _GPS_LON = 1, 2, 3, 4
_SWAPPED_ORIENTATIONS = frozenset({5, 6, 7, 8})


def _to_degrees(dms, ref: str | None) -> float | None:
    try:
        degrees, minutes, seconds = (float(part) for part in dms)
    except (TypeError, ValueError):
        return None
    value = degrees + minutes / 60 + seconds / 3600
    return -value if ref in ("S", "W") else value


def _parse_offset(raw: str | None) -> timedelta | None:
    """Parse an EXIF offset like '+02:00'. Returns None when absent or malformed."""
    if not raw or len(raw) != 6 or raw[0] not in "+-":
        return None
    try:
        hours, minutes = int(raw[1:3]), int(raw[4:6])
    except ValueError:
        return None
    delta = timedelta(hours=hours, minutes=minutes)
    return -delta if raw[0] == "-" else delta


def read_photo(path: Path) -> Photo:
    """Build a Photo from `path`, or raise SkipPhoto explaining why not."""
    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            exif = image.getexif()
            gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
            sub = exif.get_ifd(ExifTags.IFD.Exif)
            orientation = exif.get(_ORIENTATION, 1)
            camera = exif.get(_MODEL)
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise SkipPhoto(path, SkipReason.UNREADABLE) from exc

    lat = _to_degrees(gps.get(_GPS_LAT), gps.get(_GPS_LAT_REF))
    lon = _to_degrees(gps.get(_GPS_LON), gps.get(_GPS_LON_REF))
    if lat is None or lon is None:
        raise SkipPhoto(path, SkipReason.NO_GPS)

    raw_stamp = sub.get(_DATETIME_ORIGINAL)
    if not raw_stamp:
        raise SkipPhoto(path, SkipReason.NO_TIMESTAMP)
    try:
        naive_dt = datetime.strptime(str(raw_stamp), "%Y:%m:%d %H:%M:%S")
    except ValueError as exc:
        raise SkipPhoto(path, SkipReason.NO_TIMESTAMP) from exc

    if orientation in _SWAPPED_ORIENTATIONS:
        width, height = height, width

    return Photo(
        source=path,
        lat=lat,
        lon=lon,
        naive_dt=naive_dt,
        utc_offset=_parse_offset(sub.get(_OFFSET_TIME_ORIGINAL)),
        width=width,
        height=height,
        camera=str(camera).strip() if camera else None,
    )
