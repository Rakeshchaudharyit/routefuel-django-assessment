import { AppShell } from "@/components/layout/app-shell";
import { API_BASE_URL } from "@/lib/api/client";
export const metadata = { title: "RouteFuel · API Documentation" };

export default function ApiDocumentation() {
  return (
    <AppShell>
      <div className="topbar">Workspace / API Documentation</div>
      <div className="page-content documentation">
        <div className="eyebrow">DEVELOPER REFERENCE</div>
        <h1>API Documentation</h1>
        <p>RouteFuel v1 · JSON over HTTP · No authentication required.</p>
        <section className="panel">
          <h2>Endpoints</h2>
          <p>
            Configured base URL: <code>{API_BASE_URL}</code>
          </p>
          <dl>
            <dt>GET /api/v1/health/</dt>
            <dd>Liveness check. Returns status and service.</dd>
            <dt>POST /api/v1/routes/</dt>
            <dd>
              Driving route, resolved locations, geometry and provider metadata.
            </dd>
            <dt>POST /api/v1/routes/optimize/</dt>
            <dd>
              Driving route plus fuel stops, purchases and fuel-cost summary.
            </dd>
          </dl>
        </section>
        <section className="panel">
          <h2>Optimize a route</h2>
          <p>
            Required: start and finish as City, ST, City, State, or
            latitude/longitude objects. Coordinates must be within the 50 US
            states or DC.
          </p>
          <pre>
            {JSON.stringify(
              {
                start: "Dallas, TX",
                finish: "Atlanta, GA",
                vehicle: {
                  range_miles: 500,
                  mpg: 10,
                  starting_fuel_gallons: 50,
                },
                geometry_detail: "simplified",
              },
              null,
              2,
            )}
          </pre>
          <p>
            Optional vehicle settings: range_miles (above 0, up to 5000), mpg
            (above 0, up to 200), starting_fuel_gallons (0 to range ÷ MPG),
            starting_fuel_price_per_gallon ($0.50–$20.00, up to 8 decimals).
            Numeric vehicle fields must be JSON numbers; price accepts a string
            or number.
          </p>
          <p>
            Optional stop_policy.min_savings_per_stop: above $0 and up to
            $1,000, at most 2 decimals. geometry_detail accepts full or
            simplified.
          </p>
        </section>
        <section className="panel">
          <h2>Reading results</h2>
          <p>
            Money, fuel prices and gallons are decimal strings. Fuel purchases
            exclude the value of starting fuel. Display
            estimated_total_fuel_cost only when estimated_total_fuel_cost_status
            is calculated; otherwise use cost_note.
          </p>
          <p>
            Route geometry uses [longitude, latitude]. Driving time excludes
            stops. Station coordinates mark approximate town locations; address
            and road access must be checked separately.
          </p>
          <h2>Errors</h2>
          <pre>
            {
              '{"error":{"code":"location_not_found","message":"Human-readable explanation.","details":{"field":"start"}}}'
            }
          </pre>
          <p>
            Validation: 400. Location or infeasible route: 422. Provider errors:
            502 / 503 / 504. Unexpected server errors: 500. The client allows 30
            seconds for route requests.
          </p>
          <p>
            The complete source of truth is <code>docs/api-contract.md</code>.
            Import <code>docs/postman/RouteFuel.postman_collection.json</code>{" "}
            into Postman for executable examples.
          </p>
        </section>
      </div>
    </AppShell>
  );
}
