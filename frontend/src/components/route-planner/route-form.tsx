"use client";
import { useState } from "react";
import {
  ArrowDownUp,
  ArrowRight,
  ChevronDown,
  Circle,
  Flag,
  LoaderCircle,
  Route,
  SlidersHorizontal,
} from "lucide-react";
import type { OptimizeRequest } from "@/types/api";
export function RouteForm({
  loading,
  onSubmit,
  serverField,
}: {
  loading: boolean;
  onSubmit: (request: OptimizeRequest) => void;
  serverField?: string;
}) {
  const [start, setStart] = useState("");
  const [finish, setFinish] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [range, setRange] = useState("500");
  const [mpg, setMpg] = useState("10");
  const [fuel, setFuel] = useState("50");
  const [price, setPrice] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next: Record<string, string> = {};
    for (const [key, value] of [
      ["start", start],
      ["finish", finish],
    ]) {
      if (!value.trim()) next[key] = "Enter a city and state.";
      else if (!/^.+,\s*[a-zA-Z ]+$/.test(value.trim()))
        next[key] = "Use City, ST or City, State.";
    }
    if (
      start.trim() &&
      start.trim().toLowerCase() === finish.trim().toLowerCase()
    )
      next.finish = "Choose a different destination.";
    if (!range || !Number.isFinite(+range) || +range <= 0 || +range > 5000)
      next.range = "Enter a range above 0 and up to 5,000 mi.";
    if (!mpg || !Number.isFinite(+mpg) || +mpg <= 0 || +mpg > 200)
      next.mpg = "Enter MPG above 0 and up to 200.";
    if (!fuel || !Number.isFinite(+fuel) || +fuel < 0 || +fuel > +range / +mpg)
      next.fuel = "Starting fuel must fit the tank (range ÷ MPG).";
    if (
      price &&
      (!/^\d+(\.\d{1,8})?$/.test(price) || +price < 0.5 || +price > 20)
    )
      next.price = "Enter $0.50–$20.00, up to 8 decimal places.";
    setErrors(next);
    if (Object.keys(next).length) {
      setAdvanced(Boolean(next.range || next.mpg || next.fuel || next.price));
      requestAnimationFrame(() =>
        document.getElementById(Object.keys(next)[0])?.focus(),
      );
      return;
    }
    onSubmit({
      start: start.trim(),
      finish: finish.trim(),
      vehicle: {
        range_miles: +range,
        mpg: +mpg,
        starting_fuel_gallons: +fuel,
        ...(price ? { starting_fuel_price_per_gallon: price } : {}),
      },
      geometry_detail: "simplified",
    });
  }
  return (
    <section className="panel planner-panel" aria-labelledby="plan-heading">
      <div className="section-heading">
        <div>
          <span className="eyebrow">LET’S GET YOU THERE</span>
          <h2 id="plan-heading">Plan your route</h2>
        </div>
        <span className="quiet-badge">US routes</span>
      </div>
      <form onSubmit={submit} noValidate>
        <fieldset disabled={loading}>
          <div className="location-fields">
            <div className="location-field">
              <label htmlFor="start">
                <Circle size={13} className="teal-text" /> Starting location
              </label>
              <input
                id="start"
                name="start"
                placeholder="e.g. Dallas, TX"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                aria-invalid={!!errors.start || serverField === "start"}
                aria-describedby={
                  errors.start ? "start-error" : "location-hint"
                }
                autoComplete="off"
              />
              {errors.start && (
                <p className="field-error" id="start-error">
                  {errors.start}
                </p>
              )}
            </div>
            <button
              type="button"
              className="swap-button"
              onClick={() => {
                setStart(finish);
                setFinish(start);
                setErrors({});
              }}
              aria-label="Swap starting location and destination"
            >
              <ArrowDownUp size={17} />
            </button>
            <div className="location-field">
              <label htmlFor="finish">
                <Flag size={13} /> Destination
              </label>
              <input
                id="finish"
                name="finish"
                placeholder="e.g. Atlanta, GA"
                value={finish}
                onChange={(e) => setFinish(e.target.value)}
                aria-invalid={!!errors.finish || serverField === "finish"}
                aria-describedby={
                  errors.finish ? "finish-error" : "location-hint"
                }
                autoComplete="off"
              />
              {errors.finish && (
                <p className="field-error" id="finish-error">
                  {errors.finish}
                </p>
              )}
            </div>
          </div>
          <p id="location-hint" className="input-hint">
            Enter a US city and state. Locations resolve to city centers.
          </p>
          <div className="form-actions">
            <button
              type="button"
              className="text-button"
              onClick={() => setAdvanced(!advanced)}
              aria-expanded={advanced}
              aria-controls="vehicle-settings"
            >
              <SlidersHorizontal size={15} />
              Vehicle settings
              <ChevronDown size={14} className={advanced ? "rotated" : ""} />
            </button>
            <span className="vehicle-defaults">
              {range || "—"} mi range <span>·</span> {mpg || "—"} MPG
            </span>
          </div>
          {advanced && (
            <div id="vehicle-settings" className="vehicle-grid">
              {[
                {
                  id: "range",
                  label: "Maximum range (mi)",
                  value: range,
                  set: setRange,
                },
                {
                  id: "mpg",
                  label: "Fuel efficiency (MPG)",
                  value: mpg,
                  set: setMpg,
                },
                {
                  id: "fuel",
                  label: "Starting fuel (gal)",
                  value: fuel,
                  set: setFuel,
                },
                {
                  id: "price",
                  label: "Starting fuel price ($/gal, optional)",
                  value: price,
                  set: setPrice,
                },
              ].map((f) => (
                <div key={f.id}>
                  <label htmlFor={f.id}>{f.label}</label>
                  <input
                    id={f.id}
                    type="number"
                    step="any"
                    value={f.value}
                    onChange={(e) => f.set(e.target.value)}
                    aria-invalid={!!errors[f.id]}
                    aria-describedby={
                      errors[f.id] ? `${f.id}-error` : undefined
                    }
                  />
                  {errors[f.id] && (
                    <p id={`${f.id}-error`} className="field-error">
                      {errors[f.id]}
                    </p>
                  )}
                </div>
              ))}
              <p className="input-hint">
                Starting fuel cannot exceed range ÷ MPG. Add its price to
                calculate whole-trip fuel cost.
              </p>
            </div>
          )}
          <button type="submit" className="primary-button">
            {loading ? (
              <>
                <LoaderCircle size={17} className="spin" />
                Optimizing route…
              </>
            ) : (
              <>
                <Route size={17} />
                Optimize Route
                <ArrowRight size={17} />
              </>
            )}
          </button>
        </fieldset>
      </form>
    </section>
  );
}
