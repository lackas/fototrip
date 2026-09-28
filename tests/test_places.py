"""Reverse geocoding: coordinates in, a human-readable place label out.

No test here touches the network. The Geocoder takes its fetcher as an
argument, so every test supplies a stub and asserts on what the Geocoder did
with it.
"""

import json

import pytest

from fototrip.places import Geocoder, PlaceCache, label_from_address

IGUAZU_ADDRESS = {
    "tourism": "Cataratas del Iguazú",
    "town": "Puerto Iguazú",
    "state": "Misiones",
    "country": "Argentinien",
    "country_code": "ar",
}

COLOGNE_ADDRESS = {
    "road": "Domkloster",
    "suburb": "Altstadt-Nord",
    "city": "Köln",
    "state": "Nordrhein-Westfalen",
    "country": "Deutschland",
}


# ---- label_from_address ------------------------------------------------


def test_label_leads_with_a_named_attraction_and_always_ends_with_the_country():
    assert label_from_address(IGUAZU_ADDRESS) == (
        "Cataratas del Iguazú, Puerto Iguazú, Argentinien"
    )


def test_label_falls_back_to_the_settlement_when_there_is_no_attraction():
    assert label_from_address(COLOGNE_ADDRESS) == "Altstadt-Nord, Köln, Deutschland"


def test_label_uses_whatever_is_present_when_the_address_is_sparse():
    assert label_from_address({"country": "Argentinien"}) == "Argentinien"


def test_label_never_repeats_the_same_name_twice():
    """Nominatim often returns the same string under several keys."""
    address = {"town": "Salta", "city": "Salta", "state": "Salta", "country": "Argentinien"}
    assert label_from_address(address) == "Salta, Argentinien"


def test_label_is_none_for_an_address_with_nothing_usable():
    assert label_from_address({}) is None
    assert label_from_address({"country_code": "ar"}) is None


def test_label_is_capped_at_three_parts():
    label = label_from_address(IGUAZU_ADDRESS)
    assert len(label.split(", ")) == 3


# ---- PlaceCache --------------------------------------------------------


def test_unknown_coordinate_is_a_cache_miss(tmp_path):
    cache = PlaceCache(tmp_path / "places.json")
    assert cache.get(-25.6858, -54.4435) is PlaceCache.MISS


def test_stored_label_is_returned(tmp_path):
    cache = PlaceCache(tmp_path / "places.json")
    cache.put(-25.6858, -54.4435, "Cataratas del Iguazú, Misiones, Argentinien")
    assert cache.get(-25.6858, -54.4435) == "Cataratas del Iguazú, Misiones, Argentinien"


def test_a_stored_failure_is_remembered_as_none_not_as_a_miss(tmp_path):
    """A coordinate Nominatim had no name for must not be asked about again."""
    cache = PlaceCache(tmp_path / "places.json")
    cache.put(0.0, -30.0, None)
    assert cache.get(0.0, -30.0) is None


def test_nearby_coordinates_share_one_cache_entry(tmp_path):
    """Rounded to ~110 m, a burst at one spot is a single lookup."""
    cache = PlaceCache(tmp_path / "places.json")
    cache.put(-25.68581, -54.44341, "Cataratas del Iguazú, Puerto Iguazú, Argentinien")
    assert cache.get(-25.68589, -54.44349) == ("Cataratas del Iguazú, Puerto Iguazú, Argentinien")


def test_distant_coordinates_do_not_share_an_entry(tmp_path):
    cache = PlaceCache(tmp_path / "places.json")
    cache.put(-25.6858, -54.4435, "Iguazú")
    assert cache.get(-34.6037, -58.3816) is PlaceCache.MISS


def test_cache_survives_a_round_trip(tmp_path):
    path = tmp_path / "places.json"
    first = PlaceCache(path)
    first.put(-25.6858, -54.4435, "Iguazú")
    first.put(0.0, -30.0, None)
    first.save()

    second = PlaceCache(path)
    assert second.get(-25.6858, -54.4435) == "Iguazú"
    assert second.get(0.0, -30.0) is None


def test_save_creates_the_parent_directory(tmp_path):
    """The default lives under ~/.cache/fototrip/, which may not exist yet."""
    cache = PlaceCache(tmp_path / "nested" / "deeper" / "places.json")
    cache.put(-25.6858, -54.4435, "Iguazú")
    cache.save()
    assert (tmp_path / "nested" / "deeper" / "places.json").exists()


def test_corrupt_cache_file_is_ignored(tmp_path):
    path = tmp_path / "places.json"
    path.write_text("{not json")
    assert PlaceCache(path).get(-25.6858, -54.4435) is PlaceCache.MISS


def test_cache_file_holds_no_coordinates_at_full_precision(tmp_path):
    """The cache is keyed on a deliberately coarse grid, not exact positions."""
    path = tmp_path / "places.json"
    cache = PlaceCache(path)
    cache.put(-25.68581666, -54.44352222, "Iguazú")
    cache.save()
    assert "-25.68581666" not in path.read_text()
    assert list(json.loads(path.read_text())) == ["-25.686,-54.444"]


# ---- Geocoder ----------------------------------------------------------


class StubFetcher:
    """Stands in for the one HTTP call, recording how often it was made."""

    def __init__(self, address=None, error=None):
        self.address = address if address is not None else dict(IGUAZU_ADDRESS)
        self.error = error
        self.calls = []

    def __call__(self, lat, lon):
        self.calls.append((lat, lon))
        if self.error is not None:
            raise self.error
        return self.address


def test_a_miss_asks_the_fetcher_and_caches_the_answer(tmp_path):
    fetch = StubFetcher()
    geocoder = Geocoder(PlaceCache(tmp_path / "places.json"), fetch=fetch)

    assert geocoder.label_for(-25.6858, -54.4435) == (
        "Cataratas del Iguazú, Puerto Iguazú, Argentinien"
    )
    assert len(fetch.calls) == 1


def test_a_second_lookup_of_the_same_place_makes_no_request(tmp_path):
    fetch = StubFetcher()
    geocoder = Geocoder(PlaceCache(tmp_path / "places.json"), fetch=fetch)

    geocoder.label_for(-25.6858, -54.4435)
    geocoder.label_for(-25.68583, -54.44351)

    assert len(fetch.calls) == 1
    assert (geocoder.stats.cached, geocoder.stats.looked_up) == (1, 1)


def test_a_warm_cache_file_means_no_request_at_all(tmp_path):
    path = tmp_path / "places.json"
    warm = PlaceCache(path)
    warm.put(-25.6858, -54.4435, "Iguazú")
    warm.save()

    fetch = StubFetcher()
    geocoder = Geocoder(PlaceCache(path), fetch=fetch)

    assert geocoder.label_for(-25.6858, -54.4435) == "Iguazú"
    assert fetch.calls == []


def test_a_failing_request_yields_no_label_and_is_not_fatal(tmp_path):
    fetch = StubFetcher(error=OSError("no route to host"))
    geocoder = Geocoder(PlaceCache(tmp_path / "places.json"), fetch=fetch)

    assert geocoder.label_for(-25.6858, -54.4435) is None
    assert geocoder.stats.failed == 1


def test_a_failed_lookup_is_retried_on_a_later_run(tmp_path):
    """A transient network failure must not poison the cache permanently."""
    path = tmp_path / "places.json"
    failing = Geocoder(PlaceCache(path), fetch=StubFetcher(error=OSError("offline")))
    failing.label_for(-25.6858, -54.4435)
    failing.cache.save()

    fetch = StubFetcher()
    recovered = Geocoder(PlaceCache(path), fetch=fetch)
    assert recovered.label_for(-25.6858, -54.4435) == (
        "Cataratas del Iguazú, Puerto Iguazú, Argentinien"
    )
    assert len(fetch.calls) == 1


def test_a_place_with_no_usable_name_is_cached_so_it_is_asked_once(tmp_path):
    fetch = StubFetcher(address={"country_code": "ar"})
    geocoder = Geocoder(PlaceCache(tmp_path / "places.json"), fetch=fetch)

    assert geocoder.label_for(0.0, -30.0) is None
    assert geocoder.label_for(0.0, -30.0) is None
    assert len(fetch.calls) == 1
    assert geocoder.stats.unnamed == 1


def test_requests_are_spaced_to_respect_the_usage_policy(tmp_path):
    """Nominatim's policy is at most one request per second."""
    slept = []
    geocoder = Geocoder(
        PlaceCache(tmp_path / "places.json"),
        fetch=StubFetcher(),
        min_interval=1.0,
        sleep=slept.append,
        clock=lambda: 0.0,
    )

    geocoder.label_for(-25.6858, -54.4435)
    geocoder.label_for(-34.6037, -58.3816)

    assert len(slept) == 1
    assert slept[0] == pytest.approx(1.0)


def test_a_cache_hit_never_sleeps(tmp_path):
    slept = []
    geocoder = Geocoder(
        PlaceCache(tmp_path / "places.json"),
        fetch=StubFetcher(),
        min_interval=1.0,
        sleep=slept.append,
        clock=lambda: 0.0,
    )

    geocoder.label_for(-25.6858, -54.4435)
    geocoder.label_for(-25.6858, -54.4435)

    assert slept == []


def test_label_does_not_spend_both_slots_on_the_same_scale():
    """Real Nominatim data for Cologne carries suburb AND neighbourhood; naming
    two adjacent districts is less use than naming one plus the city."""
    address = {
        "suburb": "Altstadt-Nord",
        "neighbourhood": "Martinsviertel",
        "city": "Köln",
        "state": "Nordrhein-Westfalen",
        "country": "Deutschland",
    }
    assert label_from_address(address) == "Altstadt-Nord, Köln, Deutschland"


def test_label_pairs_an_attraction_with_its_town_not_its_province():
    address = {
        "tourism": "Cataratas del Iguazú",
        "suburb": "Zona Cataratas",
        "town": "Puerto Iguazú",
        "state": "Misiones",
        "country": "Argentinien",
    }
    assert label_from_address(address) == "Cataratas del Iguazú, Puerto Iguazú, Argentinien"


def test_label_collapses_stray_whitespace_from_osm_data():
    """Real OSM names contain double spaces, e.g. 'Bº  El Pilar' in Salta."""
    address = {"suburb": "Bº  El Pilar", "city": "Salta", "country": "Argentinien"}
    assert label_from_address(address) == "Bº El Pilar, Salta, Argentinien"
