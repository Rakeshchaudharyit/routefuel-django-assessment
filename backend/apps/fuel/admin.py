"""Native staff administration; model permissions govern every operation."""

from django.contrib import admin
from django.utils.html import format_html

from apps.fuel.admin_import import StationImportAdminMixin
from apps.fuel.models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(StationImportAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "opis_id",
        "city",
        "state",
        "price_usd",
        "accuracy_badge",
        "geolocated",
    )
    list_filter = ("state", "geolocation_accuracy", "geolocation_source")
    search_fields = ("name", "=opis_id", "city", "address")
    ordering = ("opis_id",)
    list_per_page = 50
    readonly_fields = ("created_at", "updated_at")
    list_display_links = ("name",)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        help_texts = {
            "opis_id": "Unique station identifier from the supplied OPIS dataset.",
            "retail_price": "USD per gallon. Stored precision is preserved.",
            "max_retail_price": "Highest observed price; must not be below the retail price.",
            "price_observations": "Number of source price observations for this station.",
            "geolocation_accuracy": "Town points are approximate; pump access is unverified.",
            "location_uncertainty_miles": "Town-level radius in miles; not detour distance.",
        }
        for name, text in help_texts.items():
            if name in form.base_fields:
                form.base_fields[name].help_text = text
        return form

    @admin.display(description="Price / gallon", ordering="retail_price")
    def price_usd(self, station: FuelStation) -> str:
        # Formatting only: show every significant stored decimal, with at least two places.
        value = format(station.retail_price, ".8f").rstrip("0")
        whole, _, fraction = value.partition(".")
        return format_html(
            '<span class="price-usd">${}</span>', whole + "." + fraction.ljust(2, "0")
        )

    @admin.display(description="Coordinate accuracy", ordering="geolocation_accuracy")
    def accuracy_badge(self, station: FuelStation) -> str:
        label = {"city": "Approximate", "unresolved": "Unresolved", "address": "Address-level"}.get(
            station.geolocation_accuracy, station.get_geolocation_accuracy_display()
        )
        return format_html(
            '<span class="status-badge status-{}" title="{}">{}</span>',
            station.geolocation_accuracy,
            station.get_geolocation_accuracy_display(),
            label,
        )

    fieldsets = (
        (
            "Station Details",
            {"fields": (("opis_id", "name"), "address", ("city", "state"), "rack_id")},
        ),
        (
            "Fuel Pricing",
            {
                "fields": (
                    ("retail_price", "max_retail_price"),
                    "price_observations",
                )
            },
        ),
        (
            "Geolocation",
            {
                "fields": (
                    ("latitude", "longitude"),
                    ("geolocation_accuracy", "geolocation_source"),
                    "location_uncertainty_miles",
                )
            },
        ),
        ("Record History", {"fields": (("created_at", "updated_at"),)}),
    )

    @admin.display(boolean=True, description="Geolocated")
    def geolocated(self, station: FuelStation) -> bool:
        return station.has_coordinates
