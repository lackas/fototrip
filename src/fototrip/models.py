"""Data carried between pipeline stages."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path


class SkipReason(StrEnum):
    NO_GPS = "no GPS coordinates"
    NO_TIMESTAMP = "no capture timestamp"
    UNREADABLE = "unreadable or truncated image"
    DUPLICATE = "the same photo twice"


class SkipPhoto(Exception):
    """Raised for a file that cannot become a Photo. Never fatal to a build."""

    def __init__(self, source: Path, reason: SkipReason) -> None:
        super().__init__(f"{source.name}: {reason}")
        self.source = source
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Photo:
    source: Path
    lat: float
    lon: float
    naive_dt: datetime
    utc_offset: timedelta | None
    width: int
    height: int
    camera: str | None
    local_dt: datetime | None = None
    day: str | None = None
    photo_id: str | None = None
    place: str | None = None

    def evolve(self, **changes) -> "Photo":
        return replace(self, **changes)
