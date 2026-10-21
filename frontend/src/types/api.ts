export type Decimal = string; // money "78.41" (2 dp), gallons "27.880" (3 dp), price "2.81233333" (>= 3 dp)

export interface ResolvedLocation {
  label: string;
  latitude: number;
  longitude: number;
  state: string; // USPS code
  source: "census_place" | "coordinates";
}

export interface FuelStop {
  sequence: number; // 1-based, in driving order
  station: {
    opis_id: number;
    name: string;
    address: string;
    city: string;
    state: string;
    latitude: number;
    longitude: number;
  }; // town-level point, NOT the pump
  location: {
    accuracy: "city" | "address"; // all current data: "city"
    source: string; // "census_gazetteer_places_2010"
    approximate: boolean; // true unless accuracy === "address"
    uncertainty_miles: number | null; // rough radius of the town
    distance_from_route_miles: number; // straight line, town point to route
  };
  route_mile: number; // miles from origin along the route (0.1)
  price_per_gallon: Decimal;
  gallons: Decimal; // bought at this stop
  cost: Decimal; // price_per_gallon x gallons, to the cent
  fuel_on_arrival_gallons: Decimal;
  fuel_on_departure_gallons: Decimal;
}

export interface OptimizeResponse {
  origin: ResolvedLocation;
  destination: ResolvedLocation;
  route: {
    distance_miles: number; // provider driving distance
    duration_minutes: number; // provider driving time, no fuel stops
    geometry: { type: "LineString"; coordinates: [number, number][] }; // [lon, lat]
    geometry_detail: "full" | "simplified";
    geometry_tolerance_meters: number | null; // 25 when simplified
  };
  vehicle: {
    range_miles: number;
    mpg: number;
    tank_capacity_gallons: Decimal;
    starting_fuel_gallons: Decimal;
    starting_fuel_price_per_gallon: Decimal | null;
  };
  fuel_plan: {
    currency: "USD";
    stops: FuelStop[]; // [] when the starting fuel covers the trip
    summary: {
      number_of_stops: number;
      total_gallons_consumed: Decimal; // distance / mpg
      starting_fuel_used_gallons: Decimal;
      total_gallons_purchased: Decimal; // sum of stop gallons
      total_purchase_cost: Decimal; // sum of stop costs = money spent at stops
      fuel_remaining_at_destination_gallons: Decimal;
      starting_fuel_value: Decimal | null;
      estimated_total_fuel_cost: Decimal | null; // whole-trip fuel cost
      estimated_total_fuel_cost_status: "calculated" | "unavailable";
      cost_note: string; // one sentence explaining the totals
    };
    stop_policy: null | {
      min_savings_per_stop: Decimal;
      stops_removed: number;
      removed_station_opis_ids: number[];
      minimum_purchase_cost: Decimal;
      minimum_cost_number_of_stops: number;
      extra_cost: Decimal;
    };
    candidates: {
      corridor_miles: number;
      stations_in_search_area: number;
      stations_on_route: number;
    };
  };
  meta: {
    provider: string;
    attribution: string;
    cached: boolean;
    routing_requests: 0 | 1;
    timings_ms: {
      route: number;
      station_matching: number;
      optimization: number;
    };
  };
}

export type LocationInput = string | { latitude: number; longitude: number };
export interface RouteRequest {
  start: LocationInput;
  finish: LocationInput;
  geometry_detail?: "full" | "simplified";
}
export interface OptimizeRequest extends RouteRequest {
  vehicle?: {
    range_miles?: number;
    mpg?: number;
    starting_fuel_gallons?: number;
    starting_fuel_price_per_gallon?: string | number;
  };
  stop_policy?: { min_savings_per_stop: string | number };
}
export interface HealthResponse {
  status: "ok";
  service: "routefuel-api";
}
export type RouteResponse = Pick<
  OptimizeResponse,
  "origin" | "destination" | "route"
> & {
  meta: Omit<OptimizeResponse["meta"], "timings_ms">;
};
export interface ApiErrorResponse {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown> | null;
  };
}
