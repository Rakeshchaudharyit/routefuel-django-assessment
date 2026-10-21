import { Fuel, Info, MapPin } from "lucide-react";
import type { FuelStop, OptimizeResponse } from "@/types/api";
import { decimal, miles, usd } from "@/lib/utils/format";
export function FuelStopCard({
  stop,
  selected = false,
  onSelect,
}: {
  stop: FuelStop;
  selected?: boolean;
  onSelect?: (id: number) => void;
}) {
  return (
    <article
      id={`fuel-stop-${stop.station.opis_id}`}
      className={`station-card ${selected ? "selected" : ""}`}
    >
      <button
        type="button"
        className="station-select"
        aria-pressed={selected}
        onClick={() => onSelect?.(stop.station.opis_id)}
        aria-label={`Select fuel stop ${stop.sequence}: ${stop.station.name}`}
      >
        <div className="station-title">
          <span className="stop-number">{stop.sequence}</span>
          <div>
            <h3>{stop.station.name}</h3>
            <p>
              {stop.station.city}, {stop.station.state}
            </p>
          </div>
        </div>
        <span className="station-select-hint">
          {selected ? "Selected on map" : "View on map"}
        </span>
      </button>
      <div className="station-mile">
        <MapPin size={13} />
        Route mile {miles(stop.route_mile)}
      </div>
      <dl className="station-values">
        <div>
          <dt>USD / gallon</dt>
          <dd>{usd(stop.price_per_gallon)}</dd>
        </div>
        <div>
          <dt>Purchase</dt>
          <dd>{decimal(stop.gallons)} gal</dd>
        </div>
        <div>
          <dt>Total · USD</dt>
          <dd>{usd(stop.cost)}</dd>
        </div>
      </dl>
      <p className="accuracy-note">
        <Info size={13} />
        {stop.location.approximate
          ? `Approximate town location${stop.location.uncertainty_miles == null ? "" : ` · ~${stop.location.uncertainty_miles} mi uncertainty`}`
          : "Address-level coordinates"}
      </p>
    </article>
  );
}
export function FuelStops({
  result,
  loading,
  selectedId = null,
  onSelect,
}: {
  result: OptimizeResponse | null;
  loading: boolean;
  selectedId?: number | null;
  onSelect?: (id: number) => void;
}) {
  return (
    <section
      className="panel stops-panel"
      aria-labelledby="stops-heading"
      aria-busy={loading}
    >
      <div className="section-heading">
        <h2 id="stops-heading">Recommended stops</h2>
        <span className="count-badge">
          {result?.fuel_plan.stops.length ?? "—"}
        </span>
      </div>
      {result ? (
        result.fuel_plan.stops.length ? (
          <div
            className="station-list"
            role="region"
            aria-label="Fuel stop cards"
            tabIndex={0}
          >
            {result.fuel_plan.stops.map((stop) => (
              <FuelStopCard
                key={stop.station.opis_id}
                stop={stop}
                selected={selectedId === stop.station.opis_id}
                onSelect={onSelect}
              />
            ))}
          </div>
        ) : (
          <div className="stops-empty">
            <Fuel size={23} />
            <h3>No fuel stops needed</h3>
            <p>Your starting fuel covers this trip.</p>
          </div>
        )
      ) : (
        <div className="stops-empty">
          <span className="empty-fuel">
            <Fuel size={24} />
          </span>
          <h3>
            {loading
              ? "Finding your fuel plan…"
              : "Good stops. Better journeys."}
          </h3>
          <p>
            {loading
              ? "The API is checking your route and fuel requirements."
              : "Your recommended fuel stops will appear here after you optimize a route."}
          </p>
          <span className="empty-dashes">
            <i />
            <i />
            <i />
          </span>
        </div>
      )}
      <div className="stops-footnote">
        <Info size={14} />
        <p>
          Station locations are approximate. Confirm the actual address and road
          access before departure. Exact road access and detour distance are
          unverified.
        </p>
      </div>
    </section>
  );
}
