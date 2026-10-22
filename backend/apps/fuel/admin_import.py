"""Admin screens for the fuel-station spreadsheet import (see apps.fuel.station_import).

Every view is wrapped by ``admin_site.admin_view`` (active staff login, CSRF protection,
no caching). Uploading/previewing needs the add or change FuelStation permission; confirming
re-checks the specific permissions the previewed changes require. Data changes only on POST.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
)
from django.shortcuts import render
from django.urls import path, reverse
from django.utils import timezone

from apps.fuel import station_import as importer
from apps.fuel.models import StationImport

MAX_LISTED_ISSUES = 100


class StationImportForm(forms.Form):
    file = forms.FileField(
        label="Station file",
        help_text="CSV UTF-8 or Excel workbook (.xlsx), up to 5 MB and 20,000 rows.",
        widget=forms.FileInput(attrs={"accept": ".csv,.xlsx"}),
    )


def format_price(value: Decimal) -> str:
    """Every significant stored decimal, at least two places ("3.459", "3.20")."""
    text = format(value, "f").rstrip("0")
    whole, _, fraction = text.partition(".")
    return f"${whole}.{fraction.ljust(2, '0')}"


def display_value(field: str, value: object) -> str:
    if value is None or value == "":
        return "(blank)"
    if field in importer.PRICE_FIELDS:
        return format_price(Decimal(str(value)))
    return str(value)


class StationImportAdminMixin:
    """Adds the "Import Fuel Stations" workflow to ``FuelStationAdmin``."""

    change_list_template = "admin/fuel/fuelstation/change_list.html"
    import_template = "admin/fuel/fuelstation/station_import.html"
    import_preview_template = "admin/fuel/fuelstation/station_import_preview.html"

    # --- permissions -------------------------------------------------------------------------

    def has_import_permission(self, request: HttpRequest) -> bool:
        return self.has_add_permission(request) or self.has_change_permission(request)

    def _require_import_permission(self, request: HttpRequest) -> None:
        if not self.has_import_permission(request):
            raise PermissionDenied

    # --- URLs --------------------------------------------------------------------------------

    def get_urls(self) -> list[Any]:
        wrap = self.admin_site.admin_view
        prefix = f"{self.opts.app_label}_{self.opts.model_name}_import"
        custom = [
            path("import/", wrap(self.import_view), name=prefix),
            path("import/template.xlsx", wrap(self.import_template_xlsx), name=f"{prefix}_xlsx"),
            path("import/template.csv", wrap(self.import_template_csv), name=f"{prefix}_csv"),
            path(
                "import/<uuid:import_id>/",
                wrap(self.import_preview_view),
                name=f"{prefix}_preview",
            ),
            path(
                "import/<uuid:import_id>/confirm/",
                wrap(self.import_confirm_view),
                name=f"{prefix}_confirm",
            ),
            path(
                "import/<uuid:import_id>/errors.csv",
                wrap(self.import_errors_view),
                name=f"{prefix}_errors",
            ),
        ]
        # Before the defaults: "<path:object_id>/" would otherwise capture "import/".
        return custom + super().get_urls()

    def changelist_view(self, request: HttpRequest, extra_context: dict | None = None):
        extra_context = {
            **(extra_context or {}),
            "has_station_import_permission": self.has_import_permission(request),
        }
        return super().changelist_view(request, extra_context)

    # --- views -------------------------------------------------------------------------------

    def _context(self, request: HttpRequest, title: str, **extra: Any) -> dict[str, Any]:
        return {
            **self.admin_site.each_context(request),
            "opts": self.opts,
            "title": title,
            "has_view_permission": self.has_view_permission(request),
            "max_upload_mb": importer.MAX_UPLOAD_BYTES // (1024 * 1024),
            "max_rows": importer.MAX_DATA_ROWS,
            "field_guide": importer.FIELD_GUIDE,
            **extra,
        }

    @staticmethod
    def _owned_import(request: HttpRequest, import_id: Any) -> StationImport:
        station_import = StationImport.objects.filter(pk=import_id, created_by=request.user).first()
        if station_import is None:
            raise Http404("Import not found.")
        return station_import

    @staticmethod
    def _preview_url(station_import: StationImport) -> str:
        return reverse("admin:fuel_fuelstation_import_preview", args=[station_import.pk])

    def import_view(self, request: HttpRequest) -> HttpResponse:
        self._require_import_permission(request)
        if request.method not in ("GET", "POST"):
            return HttpResponseNotAllowed(["GET", "POST"])
        form = StationImportForm()
        if request.method == "POST":
            form = StationImportForm(request.POST, request.FILES)
            if form.is_valid():
                upload = form.cleaned_data["file"]
                try:
                    if upload.size > importer.MAX_UPLOAD_BYTES:
                        raise importer.UploadError(importer.TOO_LARGE_MESSAGE)
                    data = b"".join(upload.chunks())
                    station_import = importer.create_preview(request.user, upload.name, data)
                except importer.UploadError as exc:
                    form.add_error("file", str(exc))
                else:
                    return HttpResponseRedirect(self._preview_url(station_import))
        context = self._context(request, "Import Fuel Stations", form=form)
        return render(request, self.import_template, context, status=400 if form.errors else 200)

    def import_preview_view(self, request: HttpRequest, import_id: Any) -> HttpResponse:
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET"])
        self._require_import_permission(request)
        station_import = self._owned_import(request, import_id)
        summary = station_import.summary
        is_pending = station_import.status == StationImport.Status.PREVIEWED
        expired = is_pending and (timezone.now() - station_import.created_at > importer.PREVIEW_TTL)
        missing = importer.missing_permissions(request.user, summary) if is_pending else []
        has_changes = bool(summary.get("new") or summary.get("updates"))
        context = self._context(
            request,
            "Import results"
            if station_import.status == StationImport.Status.APPLIED
            else "Review import",
            station_import=station_import,
            summary=summary,
            result=station_import.result,
            updates=self._display_updates(summary.get("sample_updates", [])),
            creates=self._display_creates(summary.get("sample_creates", [])),
            issues=station_import.issues[:MAX_LISTED_ISSUES],
            issue_count=len(station_import.issues),
            max_listed_issues=MAX_LISTED_ISSUES,
            expired=expired,
            missing_permissions=missing,
            can_confirm=is_pending and not expired and not missing and has_changes,
            has_changes=has_changes,
            ttl_minutes=int(importer.PREVIEW_TTL.total_seconds() // 60),
            sample_size=importer.SAMPLE_SIZE,
        )
        return render(request, self.import_preview_template, context)

    def import_confirm_view(self, request: HttpRequest, import_id: Any) -> HttpResponse:
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        self._require_import_permission(request)
        station_import = self._owned_import(request, import_id)
        try:
            station_import = importer.confirm_import(
                station_import.pk, request.user, request.POST.get("fingerprint", "")
            )
        except importer.ImportRejected as exc:
            if exc.code == "not_found":
                raise Http404("Import not found.") from exc
            messages.error(request, exc.message)
            return HttpResponseRedirect(self._preview_url(station_import))
        result = station_import.result
        messages.success(
            request,
            f"Import complete: {result['inserted']} new, {result['updated']} updated, "
            f"{result['unchanged']} unchanged, {result['rejected']} rejected rows.",
        )
        return HttpResponseRedirect(self._preview_url(station_import))

    def import_errors_view(self, request: HttpRequest, import_id: Any) -> HttpResponse:
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET"])
        self._require_import_permission(request)
        station_import = self._owned_import(request, import_id)
        response = HttpResponse(
            importer.error_report_csv(station_import), content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = (
            f'attachment; filename="station-import-{str(station_import.pk)[:8]}-errors.csv"'
        )
        return response

    def import_template_xlsx(self, request: HttpRequest) -> HttpResponse:
        self._require_import_permission(request)
        response = HttpResponse(
            importer.xlsx_template(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="fuel-stations-template.xlsx"'
        return response

    def import_template_csv(self, request: HttpRequest) -> HttpResponse:
        self._require_import_permission(request)
        response = HttpResponse(importer.csv_template(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="fuel-stations-template.csv"'
        return response

    # --- presentation ------------------------------------------------------------------------

    @staticmethod
    def _display_updates(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "opis_id": update["opis_id"],
                "name": update["name"],
                "relocate": update["relocate"],
                "had_coordinates": update["had_coordinates"],
                "changes": [
                    {
                        "label": importer.FIELD_LABELS.get(c["field"], c["field"]),
                        "old": display_value(c["field"], c["old"]),
                        "new": display_value(c["field"], c["new"]),
                    }
                    for c in update["changes"]
                ],
            }
            for update in updates
        ]

    @staticmethod
    def _display_creates(creates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {**create, "price": format_price(Decimal(create["retail_price"]))} for create in creates
        ]
