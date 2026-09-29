"""Duplicate photos, as a trip folder really produces them.

Re-adding photos to an iCloud Shared Album creates fresh assets, so an export
hands out the same shot twice under different names. One real album carried 95
such pairs. They are not a storage problem -- they are two identical pins on
the map at the same second, which is what the site is for.
"""

import json

from fototrip.dedupe import drop_duplicates
from fototrip.localtime import Localizer
from fototrip.metadata import read_photo


def _photo(
    make_jpeg,
    name,
    *,
    lat,
    lon,
    stamp,
    offset="+02:00",
    colour=(20, 80, 160),
    colour2=None,
    size=(64, 64),
):
    """A Photo through the real metadata and localtime stages, as build does."""
    path = make_jpeg(
        name,
        lat=lat,
        lon=lon,
        stamp=stamp,
        offset=offset,
        colour=colour,
        colour2=colour2,
        size=size,
    )
    return Localizer().localize(read_photo(path))


def test_two_identical_photos_at_the_same_instant_leave_one(make_jpeg):
    a = _photo(make_jpeg, "IMG_1.jpeg", lat=-25.68, lon=-54.44, stamp="2026:07:27 10:29:03")
    b = _photo(make_jpeg, "IMG_1 (1).jpeg", lat=-25.68, lon=-54.44, stamp="2026:07:27 10:29:03")

    kept, dropped = drop_duplicates([a, b])

    assert len(kept) == 1
    assert dropped == 1


def test_a_burst_of_different_shots_at_one_instant_is_kept(make_jpeg):
    """Two cameras, or a burst: same second, same spot, different pictures.

    One real album held 34 of these beside its 95 true duplicates, so dropping
    on timestamp and position alone would throw away real photographs.
    """
    a = _photo(make_jpeg, "IMG_2.jpeg", lat=-25.68, lon=-54.44, stamp="2026:07:27 10:29:03")
    b = _photo(
        make_jpeg,
        "IMG_3.jpeg",
        lat=-25.68,
        lon=-54.44,
        stamp="2026:07:27 10:29:03",
        colour2=(240, 240, 40),
    )

    kept, dropped = drop_duplicates([a, b])

    assert len(kept) == 2
    assert dropped == 0


def test_the_same_picture_at_a_different_second_is_kept(make_jpeg):
    """Identical content is not enough: a photo of the same wall a minute later
    is a different photo, and the map should show both."""
    a = _photo(make_jpeg, "IMG_4.jpeg", lat=-25.68, lon=-54.44, stamp="2026:07:27 10:29:03")
    b = _photo(make_jpeg, "IMG_5.jpeg", lat=-25.68, lon=-54.44, stamp="2026:07:27 10:30:03")

    kept, dropped = drop_duplicates([a, b])

    assert len(kept) == 2
    assert dropped == 0


def test_the_same_picture_at_a_different_place_is_kept(make_jpeg):
    a = _photo(make_jpeg, "IMG_6.jpeg", lat=-25.68, lon=-54.44, stamp="2026:07:27 10:29:03")
    b = _photo(make_jpeg, "IMG_7.jpeg", lat=-34.60, lon=-58.38, stamp="2026:07:27 10:29:03")

    kept, dropped = drop_duplicates([a, b])

    assert len(kept) == 2
    assert dropped == 0


def test_the_larger_file_is_the_one_kept(make_jpeg):
    """The shared-album copy is often the smaller re-encode of the same frame.

    Both files decode to the same picture, so either would look right on the
    map -- but one carries more of it, and that is the one the lightbox shows.
    """
    big = _photo(
        make_jpeg,
        "IMG_8.jpeg",
        lat=-25.68,
        lon=-54.44,
        stamp="2026:07:27 10:29:03",
        size=(400, 400),
    )
    small = _photo(
        make_jpeg,
        "IMG_8 (1).jpeg",
        lat=-25.68,
        lon=-54.44,
        stamp="2026:07:27 10:29:03",
        size=(64, 64),
    )
    assert big.source.stat().st_size > small.source.stat().st_size

    kept, dropped = drop_duplicates([small, big])

    assert [p.source.name for p in kept] == ["IMG_8.jpeg"]
    assert dropped == 1


def test_the_kept_order_is_the_order_it_was_given(make_jpeg):
    """Later stages rely on a stable order, so dropping must not reshuffle."""
    a = _photo(make_jpeg, "A.jpeg", lat=-25.68, lon=-54.44, stamp="2026:07:27 10:29:03")
    b = _photo(make_jpeg, "B.jpeg", lat=-34.60, lon=-58.38, stamp="2026:07:27 11:00:00")
    c = _photo(make_jpeg, "C.jpeg", lat=-25.68, lon=-54.44, stamp="2026:07:27 12:00:00")

    kept, dropped = drop_duplicates([a, b, c])

    assert [p.source.name for p in kept] == ["A.jpeg", "B.jpeg", "C.jpeg"]
    assert dropped == 0


def test_an_unreadable_file_in_a_collision_group_is_kept_not_dropped(make_jpeg, tmp_path):
    """A file that cannot be hashed must survive, not vanish silently.

    Dropping on a failed read would turn a damaged file into a missing photo
    with no entry in the report explaining it.
    """
    a = _photo(make_jpeg, "IMG_9.jpeg", lat=-25.68, lon=-54.44, stamp="2026:07:27 10:29:03")
    b = _photo(make_jpeg, "IMG_9 (1).jpeg", lat=-25.68, lon=-54.44, stamp="2026:07:27 10:29:03")
    b.source.write_bytes(b"not an image at all")

    kept, dropped = drop_duplicates([a, b])

    assert len(kept) == 2
    assert dropped == 0


def test_no_photos_is_not_an_error():
    assert drop_duplicates([]) == ([], 0)


def test_two_featureless_images_cannot_be_told_apart(make_jpeg):
    """A known and accepted limit, recorded rather than discovered later.

    The hash compares structure, and a solid colour field has none: every
    pixel equals the mean, so red and green both hash to zero and the second
    is dropped as a duplicate. It takes two photographs of nothing, at the
    same second, at the same coordinates, at the same pixel size -- and the
    alternative, a hash fine enough to separate them, would start splitting
    the two JPEG re-encodes of one frame that this exists to collapse.
    """
    a = _photo(
        make_jpeg,
        "FLAT_1.jpeg",
        lat=-25.68,
        lon=-54.44,
        stamp="2026:07:27 10:29:03",
        colour=(200, 30, 30),
    )
    b = _photo(
        make_jpeg,
        "FLAT_2.jpeg",
        lat=-25.68,
        lon=-54.44,
        stamp="2026:07:27 10:29:03",
        colour=(30, 200, 90),
    )

    kept, dropped = drop_duplicates([a, b])

    assert len(kept) == 1
    assert dropped == 1


def test_the_build_drops_duplicates_and_says_so(make_jpeg, tmp_path):
    """The module is only useful if `build` actually calls it.

    Two copies of one frame go in; one photo comes out, the duplicate is named
    in the report, and the map carries a single pin rather than two on top of
    each other.
    """
    from click.testing import CliRunner

    from fototrip.cli import main
    from fototrip.models import SkipReason

    trip = make_jpeg("IMG_1.jpeg", lat=-25.68, lon=-54.44, stamp="2026:07:27 10:29:03").parent
    make_jpeg("IMG_1 (1).jpeg", lat=-25.68, lon=-54.44, stamp="2026:07:27 10:29:03")
    make_jpeg("IMG_2.jpeg", lat=-34.60, lon=-58.38, stamp="2026:07:31 15:02:29", colour2=(9, 9, 9))

    out = tmp_path / "site"
    result = CliRunner().invoke(main, ["build", str(trip), "-o", str(out)])

    assert result.exit_code == 0, result.output
    assert str(SkipReason.DUPLICATE) in result.output
    manifest = json.loads((out / "photos.json").read_text())
    assert len(manifest["photos"]) == 2
    assert sorted(p["id"] for p in manifest["photos"]) == ["IMG_1", "IMG_2"]


def test_one_instant_written_two_ways_is_still_one_photo(make_jpeg):
    """Found in real data, and it is the project's own thesis biting back.

    A shared album handed out two copies of one frame with the capture time
    written differently: `IMG_5152.jpeg` carried 12:00:34 at +00:00 and
    `IMG_5152 (1).jpeg` carried 09:00:34 at -03:00 -- the same instant in two
    notations. A first pass at this grouped on the RAW stamp, read them as two
    different photos and left both on the map. Grouping on the resolved local
    time, which is what every other stage of this build already does, collapses
    them.
    """
    a = _photo(
        make_jpeg,
        "IMG_5152.jpeg",
        lat=-25.6804,
        lon=-54.4451,
        stamp="2026:07:20 12:00:34",
        offset="+00:00",
    )
    b = _photo(
        make_jpeg,
        "IMG_5152 (1).jpeg",
        lat=-25.6804,
        lon=-54.4451,
        stamp="2026:07:20 09:00:34",
        offset="-03:00",
    )
    assert a.naive_dt != b.naive_dt, "precondition: the raw stamps really do differ"
    assert a.local_dt == b.local_dt, "precondition: they denote one instant"

    kept, dropped = drop_duplicates([a, b])

    assert [p.source.name for p in kept] == ["IMG_5152.jpeg"]
    assert dropped == 1
