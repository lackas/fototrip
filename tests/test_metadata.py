from datetime import datetime, timedelta

import pytest

from fototrip.metadata import read_photo
from fototrip.models import SkipPhoto, SkipReason
from tests.conftest import IGUAZU


def test_reads_northern_eastern_coordinates(make_jpeg):
    photo = read_photo(make_jpeg(lat=50.9375, lon=6.9603))
    assert photo.lat == pytest.approx(50.9375, abs=1e-5)
    assert photo.lon == pytest.approx(6.9603, abs=1e-5)


def test_negates_southern_western_coordinates(make_jpeg):
    photo = read_photo(make_jpeg(lat=IGUAZU[0], lon=IGUAZU[1]))
    assert photo.lat == pytest.approx(IGUAZU[0], abs=1e-5)
    assert photo.lon == pytest.approx(IGUAZU[1], abs=1e-5)


def test_reads_timestamp_offset_dimensions_and_camera(make_jpeg):
    photo = read_photo(make_jpeg(stamp="2026:07:19 15:12:12", offset="+02:00", size=(40, 60)))
    assert photo.naive_dt == datetime(2026, 7, 19, 15, 12, 12)
    assert photo.utc_offset == timedelta(hours=2)
    assert (photo.width, photo.height) == (40, 60)
    assert photo.camera == "iPhone 14 Pro"


def test_missing_offset_is_none_not_an_error(make_jpeg):
    photo = read_photo(make_jpeg(offset=None))
    assert photo.utc_offset is None


def test_negative_offset_is_parsed(make_jpeg):
    photo = read_photo(make_jpeg(offset="-03:00"))
    assert photo.utc_offset == timedelta(hours=-3)


def test_missing_gps_is_skipped(make_jpeg):
    with pytest.raises(SkipPhoto) as excinfo:
        read_photo(make_jpeg(lat=None, lon=None))
    assert excinfo.value.reason is SkipReason.NO_GPS


def test_missing_timestamp_is_skipped(make_jpeg):
    with pytest.raises(SkipPhoto) as excinfo:
        read_photo(make_jpeg(stamp=None))
    assert excinfo.value.reason is SkipReason.NO_TIMESTAMP


def test_truncated_file_is_skipped(make_jpeg, tmp_path):
    """A JPEG still being written by Photos must not kill the build."""
    good = make_jpeg()
    truncated = tmp_path / "partial.jpeg"
    truncated.write_bytes(good.read_bytes()[:120])
    with pytest.raises(SkipPhoto) as excinfo:
        read_photo(truncated)
    assert excinfo.value.reason is SkipReason.UNREADABLE


def test_orientation_swap_is_reported_as_displayed_size(make_jpeg):
    """Orientation 6 means the stored 40x60 displays as 60x40."""
    photo = read_photo(make_jpeg(size=(40, 60), orientation=6))
    assert (photo.width, photo.height) == (60, 40)
