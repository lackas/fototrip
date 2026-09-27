from datetime import datetime, timedelta

from fototrip.localtime import Localizer
from fototrip.models import Photo
from tests.conftest import COLOGNE, IGUAZU


def _photo(lat, lon, naive, offset=timedelta(hours=2)):
    return Photo(
        source=None,
        lat=lat,
        lon=lon,
        naive_dt=naive,
        utc_offset=offset,
        width=40,
        height=60,
        camera="iPhone 14 Pro",
    )


def test_same_exif_offset_yields_different_local_days():
    """Both phones stayed on German time; the days must still be right."""
    localizer = Localizer()
    cologne = localizer.localize(_photo(*COLOGNE, datetime(2026, 7, 17, 19, 37, 59)))
    iguazu = localizer.localize(_photo(*IGUAZU, datetime(2026, 7, 19, 15, 12, 12)))
    assert cologne.local_dt.hour == 19
    assert iguazu.local_dt.hour == 10
    assert cologne.day == "2026-07-17"
    assert iguazu.day == "2026-07-19"


def test_late_argentina_evening_does_not_leak_into_next_day():
    """01:30 German time at Iguazu is 20:30 the previous evening locally."""
    result = Localizer().localize(_photo(*IGUAZU, datetime(2026, 7, 20, 1, 30)))
    assert result.day == "2026-07-19"
    assert result.local_dt.hour == 20


def test_missing_offset_treats_stamp_as_already_local():
    """A camera that records no offset is assumed to have been set to local time."""
    result = Localizer().localize(_photo(*IGUAZU, datetime(2026, 7, 19, 10, 12, 12), offset=None))
    assert result.day == "2026-07-19"
    assert result.local_dt.hour == 10
    assert result.local_dt.utcoffset() == timedelta(hours=-3)


def test_unresolvable_coordinate_falls_back_to_exif_offset(monkeypatch):
    """timezonefinder >= 9 covers the oceans, so the no-zone branch is forced here."""
    monkeypatch.setattr(Localizer, "_zone_at", lambda self, lat, lon: None)
    result = Localizer().localize(_photo(0.0, -30.0, datetime(2026, 7, 18, 12, 0, 0)))
    assert result.day == "2026-07-18"
    assert result.local_dt.utcoffset() == timedelta(hours=2)


def test_unresolvable_coordinate_without_offset_falls_back_to_utc(monkeypatch):
    monkeypatch.setattr(Localizer, "_zone_at", lambda self, lat, lon: None)
    result = Localizer().localize(_photo(0.0, -30.0, datetime(2026, 7, 18, 12, 0, 0), offset=None))
    assert result.day == "2026-07-18"
    assert result.local_dt.utcoffset() == timedelta(0)


def test_ocean_coordinate_resolves_to_an_etc_zone():
    """Mid-Atlantic is a real Etc/GMT+2 zone in timezonefinder 9, not a lookup failure."""
    result = Localizer().localize(_photo(0.0, -30.0, datetime(2026, 7, 18, 12, 0, 0)))
    assert result.day == "2026-07-18"
    assert result.local_dt.utcoffset() == timedelta(hours=-2)
