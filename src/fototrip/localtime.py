"""Turn a photo's coordinates into the local day it was taken on.

Every photo from the Argentina trip carries OffsetTimeOriginal +02:00 because the
phones stayed on German time. Grouping on the raw stamp would put evening photos
on the wrong day, so the day is derived from the coordinates instead.
"""

from datetime import timezone
from zoneinfo import ZoneInfo

from timezonefinder import TimezoneFinder

from fototrip.models import Photo


class Localizer:
    """Resolves coordinates to timezones. Construct once and reuse: TimezoneFinder
    loads a multi-megabyte data file."""

    def __init__(self) -> None:
        self._finder = TimezoneFinder()
        self._zones: dict[str, ZoneInfo] = {}

    def _zone_at(self, lat: float, lon: float) -> ZoneInfo | None:
        name = self._finder.timezone_at(lat=lat, lng=lon)
        if name is None:
            return None
        if name not in self._zones:
            self._zones[name] = ZoneInfo(name)
        return self._zones[name]

    def localize(self, photo: Photo) -> Photo:
        zone = self._zone_at(photo.lat, photo.lon)

        if zone is None:
            # Open water, or a coordinate the dataset does not cover. The camera's
            # own offset is the best remaining information; UTC if it has none.
            fallback = timezone(photo.utc_offset) if photo.utc_offset else timezone.utc
            local_dt = photo.naive_dt.replace(tzinfo=fallback)
        elif photo.utc_offset is None:
            # No offset recorded: read the stamp as already local at this place.
            local_dt = photo.naive_dt.replace(tzinfo=zone)
        else:
            instant = photo.naive_dt.replace(tzinfo=timezone(photo.utc_offset))
            local_dt = instant.astimezone(zone)

        return photo.evolve(local_dt=local_dt, day=local_dt.strftime("%Y-%m-%d"))
