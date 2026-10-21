import maplibregl, {
  type GeoJSONSource,
  type Map as MapInstance,
} from "maplibre-gl";
import type { FuelStop, OptimizeResponse } from "@/types/api";
import { decimal, miles, usd } from "@/lib/utils/format";
import { validGeometry } from "@/lib/api/validation";

function text(tag: string, value: string) {
  const el = document.createElement(tag);
  el.textContent = value;
  return el;
}
function popupContent(stop: FuelStop) {
  const el = document.createElement("div");
  el.className = "station-popup";
  el.append(
    text("strong", `${stop.sequence}. ${stop.station.name}`),
    text("p", `${stop.station.city}, ${stop.station.state}`),
    text("p", stop.station.address),
    text(
      "p",
      `${usd(stop.price_per_gallon)} / gal · ${decimal(stop.gallons)} gal`,
    ),
    text(
      "p",
      `${usd(stop.cost)} USD purchase · Route mile ${miles(stop.route_mile)}`,
    ),
    text(
      "p",
      stop.location.approximate
        ? `Approximate Census town location${stop.location.uncertainty_miles === null ? "" : ` · ~${stop.location.uncertainty_miles} mi uncertainty`}. Exact road access and detour distance are unverified.`
        : "Address-level coordinates. Confirm road access before departure.",
    ),
  );
  return el;
}
// Display the API's town-size uncertainty, not a detour or a verified station boundary.
function uncertaintyArea(stop: FuelStop): GeoJSON.Feature<GeoJSON.Polygon> {
  const { latitude: lat, longitude: lon } = stop.station;
  const distance = (stop.location.uncertainty_miles ?? 0) / 3958.76;
  const latitude = (lat * Math.PI) / 180;
  const longitude = (lon * Math.PI) / 180;
  const ring = Array.from({ length: 49 }, (_, i) => {
    const bearing = ((i % 48) * Math.PI) / 24;
    const nextLat = Math.asin(
      Math.sin(latitude) * Math.cos(distance) +
        Math.cos(latitude) * Math.sin(distance) * Math.cos(bearing),
    );
    const nextLon =
      longitude +
      Math.atan2(
        Math.sin(bearing) * Math.sin(distance) * Math.cos(latitude),
        Math.cos(distance) - Math.sin(latitude) * Math.sin(nextLat),
      );
    return [(nextLon * 180) / Math.PI, (nextLat * 180) / Math.PI];
  });
  return {
    type: "Feature",
    properties: { opis_id: stop.station.opis_id },
    geometry: { type: "Polygon", coordinates: [ring] },
  };
}

export class RouteLayer {
  private markers: maplibregl.Marker[] = [];
  private stops = new Map<number, { stop: FuelStop; el: HTMLButtonElement }>();
  private popup: maplibregl.Popup | null = null;
  private attribution: maplibregl.AttributionControl | null = null;
  private bounds: maplibregl.LngLatBounds | null = null;
  constructor(
    private map: MapInstance,
    private onSelect: (id: number) => void,
  ) {
    this.attribution = new maplibregl.AttributionControl({ compact: false });
    this.map.addControl(this.attribution, "bottom-right");
  }

  setPlan(plan: OptimizeResponse) {
    if (!validGeometry(plan.route.geometry))
      throw new Error(
        "Route geometry must contain at least two valid coordinates.",
      );
    this.clearMarkers();
    const data: GeoJSON.Feature<GeoJSON.LineString> = {
      type: "Feature",
      properties: {},
      geometry: plan.route.geometry,
    };
    const source = this.map.getSource("route") as GeoJSONSource | undefined;
    if (source) source.setData(data);
    else {
      this.map.addSource("route", { type: "geojson", data });
      this.map.addLayer({
        id: "route-outline",
        type: "line",
        source: "route",
        paint: { "line-color": "#ffffff", "line-width": 8 },
        layout: { "line-cap": "round", "line-join": "round" },
      });
      this.map.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        paint: { "line-color": "#147d70", "line-width": 5 },
        layout: { "line-cap": "round", "line-join": "round" },
      });
    }
    const uncertainty: GeoJSON.FeatureCollection<GeoJSON.Polygon> = {
      type: "FeatureCollection",
      features: plan.fuel_plan.stops
        .filter(
          (s) =>
            s.location.approximate && s.location.uncertainty_miles !== null,
        )
        .map(uncertaintyArea),
    };
    const areas = this.map.getSource("station-uncertainty") as
      GeoJSONSource | undefined;
    if (areas) areas.setData(uncertainty);
    else {
      this.map.addSource("station-uncertainty", {
        type: "geojson",
        data: uncertainty,
      });
      this.map.addLayer({
        id: "station-uncertainty-fill",
        type: "fill",
        source: "station-uncertainty",
        paint: { "fill-color": "#ae813b", "fill-opacity": 0.12 },
      });
      this.map.addLayer({
        id: "station-uncertainty-line",
        type: "line",
        source: "station-uncertainty",
        paint: {
          "line-color": "#a37b42",
          "line-width": 1,
          "line-dasharray": [3, 2],
        },
      });
    }
    for (const [location, kind, symbol] of [
      [plan.origin, "origin", "A"],
      [plan.destination, "destination", "B"],
    ] as const) {
      const el = document.createElement("button");
      el.type = "button";
      el.className = `map-marker endpoint ${kind}`;
      el.textContent = symbol;
      el.setAttribute(
        "aria-label",
        `${kind === "origin" ? "Starting location" : "Destination"}: ${location.label}`,
      );
      this.markers.push(
        new maplibregl.Marker({ element: el })
          .setLngLat([location.longitude, location.latitude])
          .setPopup(
            new maplibregl.Popup({ offset: 16 }).setText(
              `${symbol} · ${location.label}`,
            ),
          )
          .addTo(this.map),
      );
    }
    plan.fuel_plan.stops.forEach((stop) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = `map-marker stop ${stop.location.approximate ? "approximate" : ""}`;
      el.textContent = String(stop.sequence);
      el.setAttribute(
        "aria-label",
        `Fuel stop ${stop.sequence}: ${stop.station.name}, ${stop.station.city}, ${stop.station.state}${stop.location.approximate ? ", approximate town location" : ""}`,
      );
      el.setAttribute("aria-pressed", "false");
      el.onclick = (event) => {
        event.stopPropagation();
        this.select(stop.station.opis_id);
        this.onSelect(stop.station.opis_id);
      };
      this.stops.set(stop.station.opis_id, { stop, el });
      this.markers.push(
        new maplibregl.Marker({ element: el })
          .setLngLat([stop.station.longitude, stop.station.latitude])
          .addTo(this.map),
      );
    });
    if (this.attribution) this.map.removeControl(this.attribution);
    // Attribution is text from the backend, not trusted HTML.
    const safeCredit = text("span", plan.meta.attribution).innerHTML;
    this.attribution = new maplibregl.AttributionControl({
      customAttribution: safeCredit,
      compact: false,
    });
    this.map.addControl(this.attribution, "bottom-right");
    this.bounds = new maplibregl.LngLatBounds();
    plan.route.geometry.coordinates.forEach((point) =>
      this.bounds!.extend(point),
    );
    this.fit();
  }
  fit() {
    if (this.bounds && !this.bounds.isEmpty())
      this.map.fitBounds(this.bounds, {
        padding: 45,
        maxZoom: 12,
        duration: 0,
      });
  }
  select(id: number | null) {
    this.popup?.remove();
    this.popup = null;
    this.stops.forEach(({ el }, key) => {
      el.classList.toggle("selected", key === id);
      el.setAttribute("aria-pressed", String(key === id));
    });
    const selected = id === null ? undefined : this.stops.get(id);
    if (!selected) return;
    const { station } = selected.stop;
    this.popup = new maplibregl.Popup({
      offset: 20,
      maxWidth: "280px",
      anchor: "bottom",
      focusAfterOpen: false,
    })
      .setLngLat([station.longitude, station.latitude])
      .setDOMContent(popupContent(selected.stop))
      .addTo(this.map);
    this.map.easeTo({
      center: [station.longitude, station.latitude],
      padding: { top: 100, bottom: 0, left: 0, right: 0 },
      duration: 0,
    });
  }
  private clearMarkers() {
    this.popup?.remove();
    this.popup = null;
    this.stops.forEach(({ el }) => {
      el.onclick = null;
    });
    this.markers.forEach((marker) => marker.remove());
    this.markers = [];
    this.stops.clear();
  }
  destroy() {
    this.clearMarkers();
    [
      "route-line",
      "route-outline",
      "station-uncertainty-line",
      "station-uncertainty-fill",
    ].forEach((id) => {
      if (this.map.getLayer(id)) this.map.removeLayer(id);
    });
    ["route", "station-uncertainty"].forEach((id) => {
      if (this.map.getSource(id)) this.map.removeSource(id);
    });
    if (this.attribution) this.map.removeControl(this.attribution);
    this.attribution = null;
  }
}
