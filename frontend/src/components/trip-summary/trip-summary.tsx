import { Clock3, Fuel, Gauge, Route, Wallet } from "lucide-react";
import type { OptimizeResponse } from "@/types/api";
import { decimal, duration, miles, usd } from "@/lib/utils/format";
export function TripSummary({
  result,
  loading,
}: {
  result: OptimizeResponse | null;
  loading: boolean;
}) {
  const summary = result?.fuel_plan.summary;
  return (
    <section
      id="fuel-analysis"
      className="panel summary-panel"
      aria-labelledby="summary-heading"
      aria-busy={loading}
    >
      <div className="section-heading">
        <h2 id="summary-heading">Trip summary</h2>
        <Route size={18} className="muted" />
      </div>
      <p className="section-description">The road ahead, at a glance.</p>
      <div className="trip-metrics">
        <div>
          <span>
            <Route size={15} />
            Driving distance
          </span>
          <strong>{miles(result?.route.distance_miles)}</strong>
        </div>
        <div>
          <span>
            <Clock3 size={15} />
            Driving time
          </span>
          <strong>{duration(result?.route.duration_minutes)}</strong>
        </div>
      </div>
      <dl className="summary-rows">
        <div>
          <dt>
            <Gauge size={15} />
            Fuel consumed
          </dt>
          <dd>
            {summary ? `${decimal(summary.total_gallons_consumed)} gal` : "—"}
          </dd>
        </div>
        <div>
          <dt>
            <Fuel size={15} />
            Gallons purchased
          </dt>
          <dd>
            {summary ? `${decimal(summary.total_gallons_purchased)} gal` : "—"}
          </dd>
        </div>
        <div>
          <dt>
            <MapStopIcon />
            Fuel stops
          </dt>
          <dd>{summary?.number_of_stops ?? "—"}</dd>
        </div>
      </dl>
      <div className="cost-block">
        <span>
          <Wallet size={15} />
          Fuel purchases at stops <span>USD</span>
        </span>
        <strong>{usd(summary?.total_purchase_cost)}</strong>
        <div className="whole-trip">
          <span>Estimated whole-trip fuel cost</span>
          <b>
            {summary?.estimated_total_fuel_cost_status === "calculated"
              ? usd(summary.estimated_total_fuel_cost)
              : "Unavailable"}
          </b>
        </div>
      </div>
      <p className="summary-note">
        {summary?.cost_note ||
          "Optimize a route to see fuel purchases. Add a starting-fuel price for a whole-trip estimate."}
      </p>
      {result && (
        <p className="input-hint">
          Driving time excludes fuel stops. Prices use the supplied dataset, not
          live quotes.
        </p>
      )}
    </section>
  );
}
function MapStopIcon() {
  return <span className="tiny-stop" aria-hidden="true" />;
}
