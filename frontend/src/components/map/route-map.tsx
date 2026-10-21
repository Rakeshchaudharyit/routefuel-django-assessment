"use client";
import { useEffect, useRef, useState } from "react";
import maplibregl, { type Map as MapInstance } from "maplibre-gl";
import { Expand, Layers, MapPin, RotateCcw } from "lucide-react";
import type { OptimizeResponse } from "@/types/api";
import { RouteLayer } from "./route-layer";

export interface RouteMapProps {
  result: OptimizeResponse | null;
  selectedId: number | null;
  onStopSelect: (opisId: number) => void;
}
export function RouteMap({ result, selectedId, onStopSelect }: RouteMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapInstance | null>(null);
  const layer = useRef<RouteLayer | null>(null);
  const callback = useRef(onStopSelect);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    callback.current = onStopSelect;
  }, [onStopSelect]);
  const reset = () =>
    result
      ? layer.current?.fit()
      : map.current?.fitBounds(
          [
            [-125, 24],
            [-66, 50],
          ],
          { padding: 30, duration: 0 },
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
    } catch {
      const timer = setTimeout(() => setFailed(true), 0);
      return () => clearTimeout(timer);
    }
    const renderLayer = new RouteLayer(instance, (id) => callback.current(id));
    layer.current = renderLayer;
    instance.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "top-right",
    );
    const load = () => {
      setReady(true);
      setFailed(false);
    };
    const error = () => setFailed(true);
    instance.on("load", load);
    instance.on("error", error);
    const observer = new ResizeObserver(() => {
      instance.resize();
      renderLayer.fit();
    });
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      instance.off("load", load);
      instance.off("error", error);
      renderLayer.destroy();
      layer.current = null;
      map.current = null;
      instance.remove();
    };
  }, [retry]);
  useEffect(() => {
    if (ready && result) layer.current?.setPlan(result);
  }, [ready, result]);
  useEffect(() => {
    if (ready) layer.current?.select(selectedId);
  }, [ready, result, selectedId]);

  return (
    <section
      id="route-map-panel"
      className="panel map-panel"
      aria-label="Interactive route map"
    >
      <div className="map-heading">
        <div>
          <span className="live-dot" />
          <h2>Route overview</h2>
        </div>
        <span>{result ? "Optimized route" : "United States"}</span>
      </div>
      <div className="map-stage">
        <div className="map-canvas" ref={container} />
        <div className="map-tools">
          <button
            className="map-button"
            aria-label={
              result ? "Fit map to route" : "Reset map to United States"
            }
            onClick={reset}
            disabled={!ready}
          >
            <Expand size={17} />
          </button>
        </div>
        {!result && (
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
