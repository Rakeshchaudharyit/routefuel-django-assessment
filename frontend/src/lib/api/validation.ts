// Validate the wire format before React or MapLibre can consume an untrusted response.
// This validates representation, never recomputes fuel plans or prices.
type Check = (value: unknown) => boolean;
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const str: Check = (value) => typeof value === "string";
const num: Check = (value) =>
  typeof value === "number" && Number.isFinite(value);
const nonnegative: Check = (value) => num(value) && (value as number) >= 0;
const integer: Check = (value) => nonnegative(value) && Number.isInteger(value);
const bool: Check = (value) => typeof value === "boolean";
const decimal: Check = (value) =>
  typeof value === "string" && /^\d+(\.\d+)?$/.test(value);
// A policy delta can be negative by a cent after per-stop rounding of equal exact costs.
const signedDecimal: Check = (value) =>
  typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value);
const nullable =
  (check: Check): Check =>
  (value) =>
    value === null || check(value);
const oneOf =
  (...values: unknown[]): Check =>
  (value) =>
    values.includes(value);
const array =
  (check: Check): Check =>
  (value) =>
    Array.isArray(value) && value.every(check);
const shape =
  (fields: Record<string, Check>): Check =>
  (value) =>
    object(value) &&
    Object.entries(fields).every(([key, check]) => check(value[key]));
const latitude: Check = (value) =>
  num(value) && Math.abs(value as number) <= 90;
const longitude: Check = (value) =>
  num(value) && Math.abs(value as number) <= 180;
export const validGeometry: Check = (value) =>
  object(value) &&
  value.type === "LineString" &&
  Array.isArray(value.coordinates) &&
  value.coordinates.length >= 2 &&
  value.coordinates.every(
    (point) =>
      Array.isArray(point) &&
      point.length === 2 &&
      longitude(point[0]) &&
      latitude(point[1]),
  );
const location = shape({
  label: str,
  latitude,
  longitude,
  state: str,
  source: oneOf("census_place", "coordinates"),
});
const route = shape({
  distance_miles: nonnegative,
  duration_minutes: nonnegative,
  geometry: validGeometry,
  geometry_detail: oneOf("full", "simplified"),
  geometry_tolerance_meters: nullable(nonnegative),
});
const stop = shape({
  sequence: (value) => integer(value) && (value as number) > 0,
  station: shape({
    opis_id: integer,
    name: str,
    address: str,
    city: str,
    state: str,
    latitude,
    longitude,
  }),
  location: shape({
    accuracy: oneOf("city", "address"),
    source: str,
    approximate: bool,
    uncertainty_miles: nullable(nonnegative),
    distance_from_route_miles: nonnegative,
  }),
  route_mile: nonnegative,
  price_per_gallon: decimal,
  gallons: decimal,
  cost: decimal,
  fuel_on_arrival_gallons: decimal,
  fuel_on_departure_gallons: decimal,
});
const meta = {
  provider: str,
  attribution: str,
  cached: bool,
  routing_requests: oneOf(0, 1),
};
export const validRouteResponse = shape({
  origin: location,
  destination: location,
  route,
  meta: shape(meta),
});
const validPlan = shape({
  origin: location,
  destination: location,
  route,
  vehicle: shape({
    range_miles: nonnegative,
    mpg: nonnegative,
    tank_capacity_gallons: decimal,
    starting_fuel_gallons: decimal,
    starting_fuel_price_per_gallon: nullable(decimal),
  }),
  fuel_plan: shape({
    currency: oneOf("USD"),
    stops: array(stop),
    summary: shape({
      number_of_stops: integer,
      total_gallons_consumed: decimal,
      starting_fuel_used_gallons: decimal,
      total_gallons_purchased: decimal,
      total_purchase_cost: decimal,
      fuel_remaining_at_destination_gallons: decimal,
      starting_fuel_value: nullable(decimal),
      estimated_total_fuel_cost: nullable(decimal),
      estimated_total_fuel_cost_status: oneOf("calculated", "unavailable"),
      cost_note: str,
    }),
    stop_policy: nullable(
      shape({
        min_savings_per_stop: decimal,
        stops_removed: integer,
        removed_station_opis_ids: array(integer),
        minimum_purchase_cost: decimal,
        minimum_cost_number_of_stops: integer,
        extra_cost: signedDecimal,
      }),
    ),
    candidates: shape({
      corridor_miles: nonnegative,
      stations_in_search_area: integer,
      stations_on_route: integer,
    }),
  }),
  meta: shape({
    ...meta,
    timings_ms: shape({
      route: nonnegative,
      station_matching: nonnegative,
      optimization: nonnegative,
    }),
  }),
});
export function validOptimizeResponse(value: unknown): boolean {
  if (!validPlan(value)) return false;
  const plan = value as import("@/types/api").OptimizeResponse;
  const stops = plan.fuel_plan.stops;
  const summary = plan.fuel_plan.summary;
  return (
    summary.number_of_stops === stops.length &&
    new Set(stops.map((s) => s.station.opis_id)).size === stops.length &&
    stops.every(
      (s, i) =>
        s.sequence === i + 1 &&
        (i === 0 || s.route_mile >= stops[i - 1].route_mile),
    ) &&
    (summary.estimated_total_fuel_cost_status !== "calculated" ||
      summary.estimated_total_fuel_cost !== null)
  );
}
