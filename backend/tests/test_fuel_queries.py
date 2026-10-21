import pytest

from apps.fuel.models import FuelStation, GeolocationAccuracy
from apps.fuel.queries import (
    MILES_PER_DEGREE_LATITUDE,
    BoundingBox,
    routable_stations,
    stations_in_bounding_box,
)


def make(opis_id: int, lat: float | None, lng: float | None, price: str = "3.10") -> FuelStation:
    accuracy = GeolocationAccuracy.UNRESOLVED if lat is None else GeolocationAccuracy.CITY
    return FuelStation.objects.create(
        opis_id=opis_id,
        name=f"S{opis_id}",
        city="X",
        state="WI",
        rack_id=1,
        retail_price=price,
        max_retail_price=price,
        latitude=lat,
        longitude=lng,
        geolocation_accuracy=accuracy,
    )


# --- BoundingBox -----------------------------------------------------------------


def test_bounding_box_around_points_without_padding() -> None:
    box = BoundingBox.around([(40.0, -100.0), (42.0, -95.0)])

    assert box == BoundingBox(40.0, 42.0, -100.0, -95.0)


def test_bounding_box_padding_in_miles() -> None:
    box = BoundingBox.around([(40.0, -100.0)], padding_miles=69.0)

    assert box.min_latitude == pytest.approx(39.0)
    assert box.max_latitude == pytest.approx(41.0)
    # Longitude degrees are shorter than latitude degrees away from the equator.
    assert box.max_longitude - (-100.0) > 1.0


def test_bounding_box_is_clamped_to_valid_range() -> None:
    box = BoundingBox.around([(89.9, 179.9)], padding_miles=500)

    assert box.max_latitude == 90.0
    assert box.max_longitude == 180.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"points": []},
        {"points": [(91.0, 0.0)]},
        {"points": [(40.0, -100.0)], "padding_miles": -1},
    ],
)
def test_bounding_box_around_rejects_bad_input(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        BoundingBox.around(**kwargs)


def test_bounding_box_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError):
        BoundingBox(42.0, 40.0, -100.0, -95.0)


def test_miles_per_degree_constant_is_sane() -> None:
    assert 68.5 < MILES_PER_DEGREE_LATITUDE < 69.5


# --- queries -----------------------------------------------------------------------


@pytest.mark.django_db
def test_routable_stations_exclude_unresolved() -> None:
    make(1, 43.0, -90.0)
    make(2, None, None)

    assert list(routable_stations().values_list("opis_id", flat=True)) == [1]


@pytest.mark.django_db
def test_stations_in_bounding_box(django_assert_num_queries) -> None:
    make(1, 41.0, -97.0)  # inside
    make(2, 45.0, -97.0)  # north of box
    make(3, 41.0, -80.0)  # east of box
    make(4, None, None)  # unresolved
    make(5, 40.0, -100.0)  # on the boundary
    box = BoundingBox(40.0, 42.0, -100.0, -95.0)

    with django_assert_num_queries(1):
        ids = sorted(stations_in_bounding_box(box).values_list("opis_id", flat=True))

    assert ids == [1, 5]


@pytest.mark.django_db
def test_bounding_box_query_uses_coordinate_index() -> None:
    plan = stations_in_bounding_box(BoundingBox(40.0, 42.0, -100.0, -95.0)).explain()

    assert "fuel_station_lat_lng" in plan


@pytest.mark.django_db
def test_candidates_can_be_ordered_by_price() -> None:
    make(1, 41.0, -97.0, price="3.50")
    make(2, 41.5, -96.0, price="3.10")
    box = BoundingBox(40.0, 42.0, -100.0, -95.0)

    cheapest = stations_in_bounding_box(box).order_by("retail_price").first()

    assert cheapest is not None and cheapest.opis_id == 2
