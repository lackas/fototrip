"""Synthetic JPEGs with chosen GPS and timestamps, so no real photos are committed."""

from pathlib import Path

import pytest
from PIL import ExifTags, Image
from PIL.TiffImagePlugin import IFDRational

COLOGNE = (50.9375, 6.9603)
IGUAZU = (-25.6858, -54.4435)
BUENOS_AIRES = (-34.6037, -58.3816)


def _dms(value: float) -> tuple[IFDRational, IFDRational, IFDRational]:
    value = abs(value)
    degrees = int(value)
    minutes = int((value - degrees) * 60)
    seconds = (value - degrees - minutes / 60) * 3600
    return IFDRational(degrees), IFDRational(minutes), IFDRational(round(seconds, 4))


@pytest.fixture
def make_jpeg(tmp_path):
    def _make(
        name="IMG_0001.jpeg",
        *,
        lat=COLOGNE[0],
        lon=COLOGNE[1],
        stamp="2026:07:17 19:37:59",
        offset="+02:00",
        size=(40, 60),
        camera="iPhone 14 Pro",
        orientation=1,
        subdir=None,
    ) -> Path:
        exif = Image.Exif()
        if camera is not None:
            exif[0x010F] = "Apple"
            exif[0x0110] = camera
        exif[0x0112] = orientation
        sub = {}
        if stamp is not None:
            sub[0x9003] = stamp
        if offset is not None:
            sub[0x9011] = offset
        exif[ExifTags.IFD.Exif] = sub
        if lat is not None and lon is not None:
            exif[ExifTags.IFD.GPSInfo] = {
                1: "S" if lat < 0 else "N",
                2: _dms(lat),
                3: "W" if lon < 0 else "E",
                4: _dms(lon),
            }
        target = tmp_path / subdir / name if subdir else tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, "red").save(target, exif=exif)
        return target

    return _make
