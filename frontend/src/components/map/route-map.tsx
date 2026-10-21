"use client";
import { useEffect, useRef, useState } from "react";
import maplibregl, { type Map as MapInstance } from "maplibre-gl";
import { Expand, Layers, MapPin, RotateCcw } from "lucide-react";
import type { FuelStop, OptimizeResponse, ResolvedLocation } from "@/types/api";

// M5 adapter: ready for API-driven geometry and selection wiring in M6.
export interface RouteMapProps {
  geometry?: OptimizeResponse["route"]["geometry"];
  origin?: ResolvedLocation;
  destination?: ResolvedLocation;
  stops?: FuelStop[];
  attribution?: string;
  onStopSelect?: (opisId: number) => void;
}
export function RouteMap({
  geometry,
  origin,
  destination,
  stops,
  attribution,
  onStopSelect,
}: RouteMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapInstance | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const reset = () =>
    map.current?.fitBounds(
      [
        [-125, 24],
        [-66, 50],
      ],
      { padding: 30, duration: 500 },
    );
  useEffect(() => {
    if (!container.current) return;
    let instance: MapInstance;
    try {
      instance = new maplibregl.Map({
        container: container.current,
        style: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        bounds: [
          [-125, 24],
          [-66, 50],
        ],
        fitBoundsOptions: { padding: 30 },
        attributionControl: false,
      });
      map.current = instance;
      instance.addControl(
        new maplibregl.NavigationControl({ showCompass: false }),
        "top-right",
      );
      instance.addControl(
        new maplibregl.AttributionControl({ compact: false }),
        "bottom-right",
      );
      instance.on("load", () => setReady(true));
      instance.on("error", () => setFailed(true));
    } catch {
      setTimeout(() => setFailed(true), 0);
      return;
    }
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      instance.remove();
      map.current = null;
    };
  }, [retry]);

  useEffect(() => {
    const instance = map.current;
    if (!instance || !ready) return;
    const markers: maplibregl.Marker[] = [];
    const addMarker = (location: ResolvedLocation, kind: string) => {
      const el = document.createElement("div");
      el.className = `map-marker ${kind}`;
      el.title = location.label;
      markers.push(
        new maplibregl.Marker({ element: el })
          .setLngLat([location.longitude, location.latitude])
          .setPopup(new maplibregl.Popup().setText(location.label))
          .addTo(instance),
      );
    };
    if (geometry) {
      instance.addSource("route", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry },
      });
      instance.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        paint: { "line-color": "#148477", "line-width": 5 },
        layout: { "line-cap": "round", "line-join": "round" },
      });
      const bounds = new maplibregl.LngLatBounds();
      geometry.coordinates.forEach((point) => bounds.extend(point));
      if (!bounds.isEmpty())
        instance.fitBounds(bounds, { padding: 60, maxZoom: 12 });
    }
    if (origin) addMarker(origin, "origin");
    if (destination) addMarker(destination, "destination");
    stops?.forEach((stop) => {
      const el = document.createElement("button");
      el.className = `map-marker stop ${stop.location.approximate ? "approximate" : ""}`;
      el.textContent = String(stop.sequence);
      el.setAttribute(
        "aria-label",
        `${stop.station.name}, ${stop.location.approximate ? "approximate town location" : "address location"}`,
      );
      el.onclick = () => onStopSelect?.(stop.station.opis_id);
      markers.push(
        new maplibregl.Marker({ element: el })
          .setLngLat([stop.station.longitude, stop.station.latitude])
          .addTo(instance),
      );
    });
    const credit = attribution
      ? new maplibregl.AttributionControl({
          customAttribution: attribution,
          compact: false,
        })
      : null;
    if (credit) instance.addControl(credit);
    return () => {
      if (map.current !== instance) return;
      markers.forEach((marker) => marker.remove());
      if (instance.getLayer("route-line")) instance.removeLayer("route-line");
      if (instance.getSource("route")) instance.removeSource("route");
      if (credit) instance.removeControl(credit);
    };
  }, [ready, geometry, origin, destination, stops, attribution, onStopSelect]);

  return (
    <section className="panel map-panel" aria-label="Interactive route map">
      <div className="map-heading">
        <div>
          <span className="live-dot" />
          <h2>Route overview</h2>
        </div>
        <span>United States</span>
      </div>
      <div className="map-stage">
        <div className="map-canvas" ref={container} />
        <div className="map-tools">
          <button
            className="map-button"
            aria-label="Reset map to United States"
            onClick={reset}
            disabled={!ready}
          >
            <Expand size={17} />
          </button>
        </div>
        {!geometry && (
          <div className="map-empty">
            <span className="map-empty-icon">
              <MapPin size={22} />
            </span>
            <h3>Your next route starts here</h3>
            <p>
              Enter a starting location and destination
              <br />
              to plan your fuel stops.
            </p>
          </div>
        )}
        {failed && (
          <div className="map-error" role="status">
            Map tiles unavailable. Route planning is still available.
            <button
              onClick={() => {
                setFailed(false);
                setReady(false);
                setRetry((r) => r + 1);
              }}
            >
              <RotateCcw size={13} />
              Retry map
            </button>
          </div>
        )}
        <div className="map-legend">
          <Layers size={14} />
          <span>Base map</span>
          <span className="legend-divider" />
          <span className="legend-line" />
          Planned route
          <span className="legend-fuel" />
          Fuel stop
        </div>
      </div>
      <div className="map-footer">
        <MapPin size={13} />
        <span>Fuel-stop positions use approximate town-level coordinates.</span>
        <span className="map-footer-tag">MapLibre GL</span>
      </div>
    </section>
  );
}
