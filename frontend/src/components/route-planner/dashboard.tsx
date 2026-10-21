"use client";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
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
  const [submitted, setSubmitted] = useState(false);
  useEffect(() => () => controller.current?.abort(), []);
  async function submit(request: OptimizeRequest) {
    if (loading || Date.now() - lastRequest.current < 1100) return;
    lastRequest.current = Date.now();
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setLoading(true);
    setError(null);
    setResult(null);
    setSubmitted(true);
    try {
      const response = await optimizeRoute(request, current.signal);
      if (!current.signal.aborted) setResult(response);
    } catch (caught) {
      if (!current.signal.aborted)
        setError(
          caught instanceof ApiError
            ? caught
            : new ApiError("Something went wrong. Try again.", "unknown", 0),
        );
    } finally {
      if (!current.signal.aborted) {
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
                  Plan ready: {result.origin.label} → {result.destination.label}
                  . Results are shown alongside the map.
                </p>
              )}
            </div>
            <RouteMap />
            <div className="workspace-note">
              <ShieldCheck size={16} />
              <span>Built for the journey ahead.</span>
              <p>
                Fuel recommendations come from the RouteFuel optimization
                engine.
              </p>
            </div>
            {submitted && result && (
              <p className="milestone-note">
                Map route drawing and linked station selection are planned for
                M6.
              </p>
            )}
          </div>
          <aside className="results-column" aria-label="Trip results">
            <TripSummary result={result} loading={loading} />
            <FuelStops result={result} loading={loading} />
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
