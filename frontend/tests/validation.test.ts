import { describe, it, expect, vi } from "vitest";
import fixture from "./fixtures/optimized.json";
import { optimizeRoute, ApiError } from "@/lib/api/client";
import { validOptimizeResponse, validGeometry } from "@/lib/api/validation";

describe("wire-format validation", () => {
  it("accepts documented successful multi-stop responses losslessly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(fixture)));
    const result = await optimizeRoute({
      start: "Dallas, TX",
      finish: "Atlanta, GA",
      geometry_detail: "simplified",
    });
    expect(result.fuel_plan.stops).toHaveLength(2);
    expect(result.fuel_plan.stops[0].price_per_gallon).toBe("2.77566666");
    vi.unstubAllGlobals();
  });
  it.each([
    null,
    {},
    { route: {} },
    {
      ...fixture,
      route: {
        ...fixture.route,
        geometry: { type: "LineString", coordinates: [] },
      },
    },
  ])("rejects malformed success payloads: %j", async (value) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(value)));
    await expect(
      optimizeRoute({ start: "Dallas, TX", finish: "Atlanta, GA" }),
    ).rejects.toBeInstanceOf(ApiError);
    vi.unstubAllGlobals();
  });
  it("rejects out-of-range and non-finite coordinates", () => {
    for (const coordinates of [
      [
        [0, 0],
        [200, 0],
      ],
      [
        [0, 0],
        [0, NaN],
      ],
      [[0, 0]],
    ])
      expect(validGeometry({ type: "LineString", coordinates })).toBe(false);
  });
  it("accepts valid zero-stop and unavailable whole-trip costs", () => {
    const value = structuredClone(fixture);
    value.fuel_plan.stops = [];
    value.fuel_plan.summary.number_of_stops = 0;
    value.fuel_plan.summary.estimated_total_fuel_cost_status = "unavailable";
    Object.assign(value.fuel_plan.summary, {
      estimated_total_fuel_cost: null,
      starting_fuel_value: null,
    });
    expect(validOptimizeResponse(value)).toBe(true);
  });
  it("rejects duplicated, unordered stops and missing summary fields", () => {
    const value = structuredClone(fixture);
    value.fuel_plan.stops[1].station.opis_id =
      value.fuel_plan.stops[0].station.opis_id;
    expect(validOptimizeResponse(value)).toBe(false);
    value.fuel_plan.stops[1].station.opis_id = 42;
    value.fuel_plan.stops[1].sequence = 1;
    expect(validOptimizeResponse(value)).toBe(false);
    expect(
      validOptimizeResponse({
        ...fixture,
        fuel_plan: { ...fixture.fuel_plan, summary: {} },
      }),
    ).toBe(false);
  });
});

it("accepts a negative cent-rounded practical-policy delta without allowing negative purchase costs", async () => {
  // Equal exact fuel costs can have different sums after per-stop cent rounding.
  const value = {
    ...fixture,
    fuel_plan: {
      ...structuredClone(fixture.fuel_plan),
      stop_policy: {
        min_savings_per_stop: "0.10",
        stops_removed: 1,
        removed_station_opis_ids: [999],
        minimum_purchase_cost: "78.21",
        minimum_cost_number_of_stops: 3,
        extra_cost: "-0.01",
      },
    },
  };
  expect(validOptimizeResponse(value)).toBe(true);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(value)));
  const result = await optimizeRoute({ start: "Dallas, TX", finish: "Atlanta, GA" });
  expect(result.fuel_plan.stop_policy?.extra_cost).toBe("-0.01");
  vi.unstubAllGlobals();
  value.fuel_plan.summary.total_purchase_cost = "-0.01";
  expect(validOptimizeResponse(value)).toBe(false);
});
