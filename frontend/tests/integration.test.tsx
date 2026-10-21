import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  act,
  within,
} from "@testing-library/react";
import fixture from "./fixtures/optimized.json";
import type { OptimizeResponse } from "@/types/api";

const state = vi.hoisted(() => ({
  maps: [] as MockMap[],
  markers: [] as MockMarker[],
  popups: [] as MockPopup[],
}));
class MockMap {
  container: HTMLElement;
  sources = new Map<string, { setData: ReturnType<typeof vi.fn> }>();
  layers = new Map<string, unknown>();
  addSource = vi.fn((id, data) => {
    this.sources.set(id, { ...data, setData: vi.fn() });
  });
  getSource = vi.fn((id) => this.sources.get(id));
  addLayer = vi.fn((layer) => this.layers.set(layer.id, layer));
  getLayer = vi.fn((id) => this.layers.get(id));
  removeLayer = vi.fn((id) => this.layers.delete(id));
  removeSource = vi.fn((id) => this.sources.delete(id));
  addControl = vi.fn();
  removeControl = vi.fn();
  fitBounds = vi.fn();
  easeTo = vi.fn();
  resize = vi.fn();
  off = vi.fn();
  remove = vi.fn();
  on = vi.fn((event, fn) => {
    if (event === "load") queueMicrotask(fn);
  });
  constructor({ container }: { container: HTMLElement }) {
    this.container = container;
    state.maps.push(this);
  }
}
class MockMarker {
  el: HTMLElement;
  removed = false;
  coordinates: number[] = [];
  constructor({ element }: { element: HTMLElement }) {
    this.el = element;
    state.markers.push(this);
  }
  setLngLat(value: number[]) {
    this.coordinates = value;
    return this;
  }
  setPopup() {
    return this;
  }
  addTo(map: MockMap) {
    map.container.append(this.el);
    return this;
  }
  remove() {
    this.removed = true;
    this.el.remove();
  }
}
class MockPopup {
  content: HTMLElement | null = null;
  constructor() {
    state.popups.push(this);
  }
  setText() {
    return this;
  }
  setLngLat() {
    return this;
  }
  setDOMContent(content: HTMLElement) {
    this.content = content;
    return this;
  }
  addTo() {
    return this;
  }
  remove = vi.fn();
}
vi.mock("maplibre-gl", () => ({
  default: {
    get Map() {
      return MockMap;
    },
    get Marker() {
      return MockMarker;
    },
    get Popup() {
      return MockPopup;
    },
    NavigationControl: class {},
    AttributionControl: class {},
    LngLatBounds: class {
      points: unknown[] = [];
      extend(p: unknown) {
        this.points.push(p);
        return this;
      }
      isEmpty() {
        return !this.points.length;
      }
    },
  },
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));
vi.mock("next/dynamic", async () => {
  const { RouteMap } = await import("@/components/map/route-map");
  return { default: () => RouteMap };
});
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    optimizeRoute: vi.fn(),
    getHealth: vi
      .fn()
      .mockResolvedValue({ status: "ok", service: "routefuel-api" }),
  };
});
import { RouteMap } from "@/components/map/route-map";
import { Dashboard } from "@/components/route-planner/dashboard";
import { RouteForm } from "@/components/route-planner/route-form";
import { TripSummary } from "@/components/trip-summary/trip-summary";
import { FuelStops } from "@/components/fuel-stops/fuel-stops";
import { optimizeRoute, ApiError } from "@/lib/api/client";
const plan = () => structuredClone(fixture) as OptimizeResponse;
const optimized = vi.mocked(optimizeRoute);
beforeEach(() => {
  state.maps.length = 0;
  state.markers.length = 0;
  state.popups.length = 0;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  Element.prototype.scrollIntoView = vi.fn();
  optimized.mockReset();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const fillRoute = () => {
  fireEvent.change(screen.getByLabelText("Starting location"), {
    target: { value: "Dallas, TX" },
  });
  fireEvent.change(screen.getByLabelText("Destination", { exact: true }), {
    target: { value: "Atlanta, GA" },
  });
};

describe("MapLibre route integration", () => {
  it("draws actual geometry, distinct endpoints, ordered stops and uncertainty areas", async () => {
    render(
      <RouteMap result={plan()} selectedId={null} onStopSelect={vi.fn()} />,
    );
    await waitFor(() =>
      expect(state.maps[0].addSource).toHaveBeenCalledTimes(2),
    );
    const map = state.maps[0];
    expect(map.addSource.mock.calls[0][1].data.geometry).toEqual(
      fixture.route.geometry,
    );
    expect(map.layers.has("route-line")).toBe(true);
    expect(map.fitBounds).toHaveBeenCalled();
    expect(state.markers.map((m) => m.coordinates)).toEqual([
      [fixture.origin.longitude, fixture.origin.latitude],
      [fixture.destination.longitude, fixture.destination.latitude],
      ...fixture.fuel_plan.stops.map((s) => [
        s.station.longitude,
        s.station.latitude,
      ]),
    ]);
    expect(
      screen.getByRole("button", { name: /Starting location: Dallas/ }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /Destination: Atlanta/ }),
    ).toBeTruthy();
    expect(state.markers.slice(2).map((m) => m.el.textContent)).toEqual([
      "1",
      "2",
    ]);
    expect(
      map.addControl.mock.calls.some((call) => call[1] === "bottom-right"),
    ).toBe(true);
  });
  it("selects a card's marker without recreating the map, markers or source", async () => {
    const result = plan();
    const select = vi.fn();
    const { rerender } = render(
      <RouteMap result={result} selectedId={null} onStopSelect={select} />,
    );
    await waitFor(() => expect(state.markers).toHaveLength(4));
    rerender(
      <RouteMap result={result} selectedId={64558} onStopSelect={select} />,
    );
    expect(
      screen
        .getByRole("button", { name: /Fuel stop 2/ })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(state.maps).toHaveLength(1);
    expect(state.markers).toHaveLength(4);
    expect(state.maps[0].addSource).toHaveBeenCalledTimes(2);
    expect(state.popups.at(-1)?.content?.textContent).toContain(
      "Exact road access and detour distance are unverified",
    );
    expect(state.maps[0].easeTo).toHaveBeenCalledWith(
      expect.objectContaining({ center: [-88.68944, 32.384191] }),
    );
  });
  it("marker selection emits the matching station ID and safe details", async () => {
    const select = vi.fn();
    render(
      <RouteMap result={plan()} selectedId={null} onStopSelect={select} />,
    );
    await waitFor(() => expect(state.markers).toHaveLength(4));
    const bubbled = vi.fn();
    state.maps[0].container.addEventListener("click", bubbled);
    fireEvent.click(screen.getByRole("button", { name: /Fuel stop 1/ }));
    expect(bubbled).not.toHaveBeenCalled();
    expect(select).toHaveBeenCalledWith(60540);
    expect(state.popups.at(-1)?.content?.textContent).toContain("$15.78");
    expect(state.popups.at(-1)?.content?.textContent).toContain("5.685 gal");
  });
  it("updates the route source, removes old markers and cleans up on unmount", async () => {
    const { rerender, unmount } = render(
      <RouteMap result={plan()} selectedId={null} onStopSelect={vi.fn()} />,
    );
    await waitFor(() => expect(state.markers).toHaveLength(4));
    const old = state.markers.slice();
    const map = state.maps[0];
    const source = map.sources.get("route");
    const next = plan();
    next.fuel_plan.stops = [];
    next.fuel_plan.summary.number_of_stops = 0;
    rerender(
      <RouteMap result={next} selectedId={null} onStopSelect={vi.fn()} />,
    );
    expect(old.every((m) => m.removed)).toBe(true);
    expect(source?.setData).toHaveBeenCalledTimes(1);
    expect(state.markers.filter((m) => !m.removed)).toHaveLength(2);
    expect(state.maps).toHaveLength(1);
    unmount();
    expect(map.off).toHaveBeenCalledTimes(2);
    expect(map.remove).toHaveBeenCalledTimes(1);
    expect(map.sources.size).toBe(0);
  });
  it("handles a 20,000-point line in one source update", async () => {
    const next = plan();
    const [a, b] = next.route.geometry.coordinates;
    next.route.geometry.coordinates = Array.from({ length: 20000 }, (_, i) => [
      a[0] + ((b[0] - a[0]) * i) / 19999,
      a[1] + ((b[1] - a[1]) * i) / 19999,
    ]);
    render(<RouteMap result={next} selectedId={null} onStopSelect={vi.fn()} />);
    await waitFor(() =>
      expect(state.maps[0].addSource).toHaveBeenCalledTimes(2),
    );
    expect(
      state.maps[0].addSource.mock.calls[0][1].data.geometry.coordinates,
    ).toHaveLength(20000);
  });
});

describe("form and result presentation", () => {
  it("validates required fields and submits only on request", () => {
    const submit = vi.fn();
    render(<RouteForm loading={false} onSubmit={submit} />);
    fireEvent.click(screen.getByRole("button", { name: "Optimize Route" }));
    expect(screen.getAllByText("Enter a city and state.")).toHaveLength(2);
    expect(submit).not.toHaveBeenCalled();
    fillRoute();
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Optimize Route" }));
    expect(submit).toHaveBeenCalledWith({
      start: "Dallas, TX",
      finish: "Atlanta, GA",
      vehicle: { range_miles: 500, mpg: 10, starting_fuel_gallons: 50 },
      geometry_detail: "simplified",
    });
  });
  it("validates tank capacity and optional stop policy", () => {
    const submit = vi.fn();
    render(<RouteForm loading={false} onSubmit={submit} />);
    fillRoute();
    fireEvent.click(screen.getByRole("button", { name: "Vehicle settings" }));
    fireEvent.change(screen.getByLabelText("Starting fuel (gal)"), {
      target: { value: "51" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Optimize Route" }));
    expect(submit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Starting fuel (gal)"), {
      target: { value: "0" },
    });
    fireEvent.change(
      screen.getByLabelText("Minimum savings per stop ($, optional)"),
      { target: { value: "2.00" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Optimize Route" }));
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({
        stop_policy: { min_savings_per_stop: "2.00" },
      }),
    );
  });
  it("uses API summary values, USD strings and remaining fuel without recomputing", () => {
    render(<TripSummary result={plan()} loading={false} />);
    expect(screen.getByText("778.8 mi")).toBeTruthy();
    expect(screen.getByText("77.880 gal")).toBeTruthy();
    expect(screen.getByText("0.000 gal")).toBeTruthy();
    expect(screen.getByText("$78.20")).toBeTruthy();
    expect(screen.getByText("$238.15")).toBeTruthy();
  });
  it("does not substitute zero for an unavailable whole-trip cost", () => {
    const next = plan();
    next.fuel_plan.summary.estimated_total_fuel_cost_status = "unavailable";
    next.fuel_plan.summary.estimated_total_fuel_cost = null;
    next.fuel_plan.summary.cost_note = "Starting fuel price is unknown.";
    render(<TripSummary result={next} loading={false} />);
    expect(screen.getByText("Unavailable")).toBeTruthy();
    expect(screen.getByText("Starting fuel price is unknown.")).toBeTruthy();
    expect(screen.queryByText("$0.00")).toBeNull();
  });
  it("supports card selection and successful zero-stop journeys", () => {
    const select = vi.fn();
    const { rerender } = render(
      <FuelStops
        result={plan()}
        loading={false}
        selectedId={60540}
        onSelect={select}
      />,
    );
    const button = screen.getByRole("button", { name: /Select fuel stop 1/ });
    expect(button.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(button);
    expect(select).toHaveBeenCalledWith(60540);
    const next = plan();
    next.fuel_plan.stops = [];
    next.fuel_plan.summary.number_of_stops = 0;
    rerender(<FuelStops result={next} loading={false} />);
    expect(screen.getByText("No fuel stops needed")).toBeTruthy();
  });
});

describe("dashboard request lifecycle", () => {
  it("prevents repeated submissions, displays loading and links both selection directions", async () => {
    let resolve!: (value: OptimizeResponse) => void;
    optimized.mockImplementation(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    render(<Dashboard />);
    fillRoute();
    fireEvent.click(screen.getByRole("button", { name: "Optimize Route" }));
    const pending = screen.getByRole("button", { name: "Optimizing route…" });
    expect(
      (pending as HTMLButtonElement).disabled ||
        pending.closest("fieldset")?.disabled,
    ).toBe(true);
    fireEvent.click(pending);
    expect(optimized).toHaveBeenCalledTimes(1);
    expect(
      screen.getByText("Calculating your route and fuel purchases…"),
    ).toBeTruthy();
    await act(async () => resolve(plan()));
    await waitFor(() =>
      expect(state.markers.filter((m) => !m.removed)).toHaveLength(4),
    );
    fireEvent.click(screen.getByRole("button", { name: /Select fuel stop 2/ }));
    expect(
      screen
        .getByRole("button", { name: /^Fuel stop 2/ })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: /^Fuel stop 1/ }));
    expect(
      screen
        .getByRole("button", { name: /Select fuel stop 1/ })
        .getAttribute("aria-pressed"),
    ).toBe("true");
  });
  it.each([
    ["network_error", "Cannot reach API"],
    ["client_timeout", "Request timed out"],
    ["routing_unavailable", "OSRM unavailable"],
    ["no_feasible_fuel_plan", "No feasible fuel plan"],
    ["route_not_found", "No driving route"],
    ["invalid_response", "Invalid response"],
    ["location_not_found", "Unknown destination"],
  ])("presents %s clearly", async (code, message) => {
    optimized.mockRejectedValue(
      new ApiError(
        message,
        code,
        503,
        code === "location_not_found" ? { field: "finish" } : null,
      ),
    );
    render(<Dashboard />);
    fillRoute();
    fireEvent.click(screen.getByRole("button", { name: "Optimize Route" }));
    await waitFor(() =>
      expect(within(screen.getByRole("alert")).getByText(message)).toBeTruthy(),
    );
    if (code === "location_not_found")
      expect(
        screen
          .getByLabelText("Destination", { exact: true })
          .getAttribute("aria-invalid"),
      ).toBe("true");
  });
  it("queues an immediate deliberate retry instead of dropping it", async () => {
    optimized.mockResolvedValue(plan());
    render(<Dashboard />);
    fillRoute();
    fireEvent.click(screen.getByRole("button", { name: "Optimize Route" }));
    await screen.findByText("$78.20");
    fireEvent.click(screen.getByRole("button", { name: "Optimize Route" }));
    expect(
      screen.getByText("Calculating your route and fuel purchases…"),
    ).toBeTruthy();
    await waitFor(() => expect(optimized).toHaveBeenCalledTimes(2), {
      timeout: 1800,
    });
    await waitFor(() =>
      expect(
        screen.queryByText("Calculating your route and fuel purchases…"),
      ).toBeNull(),
    );
  });
  it("preserves a valid plan when a subsequent request fails", async () => {
    const now = vi.spyOn(Date, "now");
    now.mockReturnValue(2000);
    optimized.mockResolvedValueOnce(plan());
    render(<Dashboard />);
    fillRoute();
    fireEvent.click(screen.getByRole("button", { name: "Optimize Route" }));
    await screen.findByText("$78.20");
    now.mockReturnValue(4000);
    optimized.mockRejectedValueOnce(
      new ApiError("OSRM unavailable", "routing_unavailable", 503),
    );
    fireEvent.click(screen.getByRole("button", { name: "Optimize Route" }));
    await screen.findByRole("alert");
    expect(screen.getByText("$78.20")).toBeTruthy();
    expect(screen.getByText(/Showing previous valid plan/)).toBeTruthy();
    expect(state.maps).toHaveLength(1);
  });
});
