from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.fuel.constants import PRICE_DECIMAL_PLACES, PRICE_MAX_DIGITS


class GeolocationAccuracy(models.TextChoices):
    """How precisely ``latitude``/``longitude`` locate the actual truck stop."""

    UNRESOLVED = "unresolved", "Unresolved"
    # Point inside the station's city/town, not the station itself.
    CITY = "city", "City-level approximation"
    # Reserved for future enrichment with real station positions.
    ADDRESS = "address", "Address-level"


class GeolocationSource(models.TextChoices):
    NONE = "", "None"
    CENSUS_GAZETTEER_PLACES_2010 = "census_gazetteer_places_2010", "US Census 2010 Gazetteer"


class FuelStation(models.Model):
    """One truck stop, keyed by its OPIS ID, with its best listed retail price."""

    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    rack_id = models.PositiveIntegerField()

    # Lowest price listed for this station in the source file (USD per gallon).
    retail_price = models.DecimalField(
        max_digits=PRICE_MAX_DIGITS, decimal_places=PRICE_DECIMAL_PLACES
    )
    # Highest listed price and number of price rows, so the merge stays transparent.
    max_retail_price = models.DecimalField(
        max_digits=PRICE_MAX_DIGITS, decimal_places=PRICE_DECIMAL_PLACES
    )
    price_observations = models.PositiveSmallIntegerField(default=1)

    latitude = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-90.0), MaxValueValidator(90.0)],
    )
    longitude = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-180.0), MaxValueValidator(180.0)],
    )
    geolocation_source = models.CharField(
        max_length=40, choices=GeolocationSource.choices, default=GeolocationSource.NONE, blank=True
    )
    geolocation_accuracy = models.CharField(
        max_length=12,
        choices=GeolocationAccuracy.choices,
        default=GeolocationAccuracy.UNRESOLVED,
    )
    # Rough radius (miles) within which the real station is expected to be, for approximate
    # coordinates. Derived from the matched place's land area; null when unresolved.
    location_uncertainty_miles = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["opis_id"]
        indexes = [
            models.Index(fields=["state", "city"], name="fuel_station_state_city"),
            models.Index(fields=["latitude", "longitude"], name="fuel_station_lat_lng"),
            models.Index(fields=["retail_price"], name="fuel_station_price"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(retail_price__gt=0) & Q(max_retail_price__gte=models.F("retail_price")),
                name="fuel_station_price_valid",
            ),
            models.CheckConstraint(
                condition=Q(latitude__isnull=True) | Q(latitude__gte=-90, latitude__lte=90),
                name="fuel_station_latitude_range",
            ),
            models.CheckConstraint(
                condition=Q(longitude__isnull=True) | Q(longitude__gte=-180, longitude__lte=180),
                name="fuel_station_longitude_range",
            ),
            # An unresolved station never carries coordinates, and a resolved one always does.
            models.CheckConstraint(
                condition=(
                    Q(
                        geolocation_accuracy=GeolocationAccuracy.UNRESOLVED,
                        latitude__isnull=True,
                        longitude__isnull=True,
                    )
                    | (
                        ~Q(geolocation_accuracy=GeolocationAccuracy.UNRESOLVED)
                        & Q(latitude__isnull=False, longitude__isnull=False)
                    )
                ),
                name="fuel_station_geolocation_consistent",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state}) #{self.opis_id}"

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None
