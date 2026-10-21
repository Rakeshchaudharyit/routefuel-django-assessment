"use client";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  CircleAlert,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { RouteForm } from "./route-form";
import { TripSummary } from "@/components/trip-summary/trip-summary";
import { FuelStops } from "@/components/fuel-stops/fuel-stops";
import { ApiError, optimizeRoute } from "@/lib/api/client";
import { useHealth } from "@/hooks/use-health";
import type { OptimizeRequest, OptimizeResponse } from "@/types/api";
const RouteMap = dynamic(
  () => import("@/components/map/route-map").then((module) => module.RouteMap),
  {
    ssr: false,
    loading: () => (
      <div className="panel map-placeholder">Loading interactive map…</div>
    ),
  },
);
export function Dashboard() {
  const { status, refresh } = useHealth();
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<OptimizeResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const controller = useRef<AbortController | null>(null);
  const lastRequest = useRef(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selectFromMap = useCallback((id: number) => {
    setSelectedId(id);
    document
      .getElementById(`fuel-stop-${id}`)
      ?.scrollIntoView({ block: "nearest", behavior: "instant" });
  }, []);
  const selectFromCard = useCallback((id: number) => {
    setSelectedId(id);
    document
      .getElementById("route-map-panel")
      ?.scrollIntoView({ block: "nearest", behavior: "instant" });
  }, []);
  useEffect(() => () => controller.current?.abort(), []);
  async function submit(request: OptimizeRequest) {
    if (controller.current) return;
    const current = new AbortController();
    controller.current = current;
    setLoading(true);
    setError(null);

    try {
      // Queue rapid follow-up submissions so the provider's 1 request/second
      // limit does not silently discard a deliberate user action.
      const delay = Math.max(0, 1100 - (Date.now() - lastRequest.current));
      if (delay > 0)
        await new Promise<void>((resolve) => {
          const finish = () => {
            clearTimeout(timer);
            current.signal.removeEventListener("abort", finish);
            resolve();
          };
          const timer = setTimeout(finish, delay);
          current.signal.addEventListener("abort", finish, { once: true });
        });
      if (current.signal.aborted) return;
      lastRequest.current = Date.now();
      const response = await optimizeRoute(request, current.signal);
      if (!current.signal.aborted) {
        setResult(response);
        setSelectedId(null);
      }
    } catch (caught) {
      if (!current.signal.aborted)
        setError(
          caught instanceof ApiError
            ? caught
            : new ApiError("Something went wrong. Try again.", "unknown", 0),
        );
    } finally {
      if (!current.signal.aborted) {
        controller.current = null;
        setLoading(false);
        void refresh();
      }
    }
  }
  return (
    <AppShell>
      <div className="topbar">
        <span>
          Workspace <span>/</span> <b>Route Planner</b>
        </span>
        <span className="topbar-end">US route optimization</span>
      </div>
      <div className="page-content">
        <header className="page-header">
          <div>
            <div className="eyebrow">EVERY MILE MATTERS</div>
            <h1>Route Planner</h1>
            <p>
              Plan the drive. Find the right stops. Keep fuel costs in view.
            </p>
          </div>
          <button
            className={`connection-status ${status}`}
            onClick={() => void refresh()}
            disabled={status === "checking"}
            title="Check API connection"
          >
            <span className="status-dot" />
            {status === "connected"
              ? "API connected"
              : status === "checking"
                ? "Checking API"
                : "API disconnected"}
            <RefreshCw
              size={12}
              className={status === "checking" ? "spin" : ""}
            />
          </button>
        </header>
        {status === "disconnected" && (
          <div className="connection-banner" role="status">
            <CircleAlert size={16} />
            <span>
              <b>API unavailable.</b> Start Django at your configured API
              address, then check the connection again.
            </span>
          </div>
        )}
        <div className="dashboard-grid">
          <div className="route-workspace">
            <RouteForm
              loading={loading}
              onSubmit={submit}
              serverErrors={apiFieldErrors(error)}
              serverField={
                typeof error?.details?.field === "string"
                  ? error.details.field
                  : undefined
              }
            />
            <div aria-live="polite" aria-atomic="true">
              {loading && (
                <div className="loading-banner">
                  <LoaderCircle size={16} className="spin" />
                  Calculating your route and fuel purchases…
                </div>
              )}
              {error && (
                <div className="error-banner" role="alert">
                  <CircleAlert size={18} />
                  <div>
                    <strong>We couldn’t optimize this route</strong>
                    <p>{error.message}</p>
                    {error.details && (
                      <details>
                        <summary>View API details</summary>
                        <pre>{JSON.stringify(error.details, null, 2)}</pre>
                      </details>
                    )}
                  </div>
                </div>
              )}
              {result && (
                <p className="result-banner">
                  {loading || error
                    ? "Showing previous valid plan: "
                    : "Plan ready: "}
                  {result.origin.label} → {result.destination.label}.
                  {loading
                    ? " A new plan is being calculated."
                    : error
                      ? " The latest request did not replace these results."
                      : ` ${result.meta.cached ? "Cached route" : "Fresh route"} · ${result.meta.provider.toUpperCase()}.`}
                </p>
              )}
            </div>
            <RouteMap
              result={result}
              selectedId={selectedId}
              onStopSelect={selectFromMap}
            />
            <div className="workspace-note">
              <ShieldCheck size={16} />
              <span>Built for the journey ahead.</span>
              <p>
                Fuel recommendations come from the RouteFuel optimization
                engine.
              </p>
            </div>
          </div>
          <aside className="results-column" aria-label="Trip results">
            <TripSummary result={result} loading={loading} />
            <FuelStops
              result={result}
              loading={loading}
              selectedId={selectedId}
              onSelect={selectFromCard}
            />
          </aside>
        </div>
        <footer className="page-footer">
          <span>
            RouteFuel <span> / </span> Smarter planning, mile after mile.
          </span>
          <span>
            Distances in miles <span>·</span> Costs in USD
          </span>
        </footer>
      </div>
    </AppShell>
  );
}

function apiFieldErrors(error: ApiError | null): Record<string, string> {
  if (!error?.details) return {};
  if (typeof error.details.field === "string")
    return { [error.details.field]: error.message };
  const fields: Record<string, string> = {};
  const names: Record<string, string> = {
    range_miles: "range",
    starting_fuel_gallons: "fuel",
    starting_fuel_price_per_gallon: "price",
    min_savings_per_stop: "savings",
  };
  const visit = (value: unknown) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return;
    Object.entries(value).forEach(([key, entry]) => {
      if (Array.isArray(entry))
        fields[names[key] || key] = entry
          .filter((item) => typeof item === "string")
          .join(" ");
      else if (typeof entry === "string") fields[names[key] || key] = entry;
      else visit(entry);
    });
  };
  visit(error.details);
  return fields;
}
