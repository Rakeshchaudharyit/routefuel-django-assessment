import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
async function load(path) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  let compiled = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ES2022,
    },
  }).outputText;
  if (path.endsWith("client.ts")) {
    const validation = await readFile(
      new URL("../src/lib/api/validation.ts", import.meta.url),
      "utf8",
    );
    const js = ts.transpileModule(validation, {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.ES2022,
      },
    }).outputText;
    compiled = compiled.replace(
      '"./validation"',
      JSON.stringify(
        `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`,
      ),
    );
  }
  return import(
    `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
  );
}
const api = await load("../src/lib/api/client.ts");
const format = await load("../src/lib/utils/format.ts");
test("decimal money preserves every backend digit and distinguishes missing from zero", () => {
  assert.equal(format.usd("1234.12345678"), "$1,234.12345678");
  assert.equal(format.usd("0.00"), "$0.00");
  assert.equal(format.usd(null), "—");
  assert.equal(format.duration(119.6), "2h 0m");
});
test("client request, errors, timeout and cancellation", async (t) => {
  const original = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = original;
  });
  await t.test(
    "sends exact optimizer schema and retains decimal strings",
    async () => {
      globalThis.fetch = async (url, options) => {
        assert.equal(url, `${api.API_BASE_URL}/api/v1/routes/optimize/`);
        assert.equal(options.method, "POST");
        assert.deepEqual(JSON.parse(options.body), {
          start: "Dallas, TX",
          finish: "Atlanta, GA",
          geometry_detail: "simplified",
        });
        const fixture = JSON.parse(
          await readFile(
            new URL("./fixtures/optimized.json", import.meta.url),
            "utf8",
          ),
        );
        fixture.fuel_plan.summary.total_purchase_cost = "78.41";
        return Response.json(fixture);
      };
      const response = await api.optimizeRoute({
        start: "Dallas, TX",
        finish: "Atlanta, GA",
        geometry_detail: "simplified",
      });
      assert.equal(response.fuel_plan.summary.total_purchase_cost, "78.41");
    },
  );
  await t.test("retains field errors from Django", async () => {
    globalThis.fetch = async () =>
      Response.json(
        {
          error: {
            code: "location_not_found",
            message: "Unknown city.",
            details: { field: "start" },
          },
        },
        { status: 422 },
      );
    await assert.rejects(
      api.request("/test"),
      (e) =>
        e instanceof api.ApiError &&
        e.status === 422 &&
        e.details.field === "start",
    );
  });
  await t.test("maps connection failures", async () => {
    globalThis.fetch = async () => {
      throw new TypeError("Failed to fetch");
    };
    await assert.rejects(api.getHealth(), (e) => e.code === "network_error");
  });
  await t.test("rejects a different health service", async () => {
    globalThis.fetch = async () =>
      Response.json({ status: "ok", service: "other-api" });
    await assert.rejects(api.getHealth(), (e) => e.code === "invalid_response");
  });
  await t.test(
    "distinguishes deadline expiry and caller cancellation",
    async () => {
      globalThis.fetch = async (_, { signal }) =>
        new Promise((resolve, reject) => {
          const abort = () => reject(new DOMException("Aborted", "AbortError"));
          if (signal.aborted) abort();
          else signal.addEventListener("abort", abort, { once: true });
        });
      await assert.rejects(
        api.request("/test", {}, 5),
        (e) => e.code === "client_timeout",
      );
      const controller = new AbortController();
      controller.abort();
      await assert.rejects(
        api.request("/test", { signal: controller.signal }),
        (e) => e.code === "cancelled",
      );
    },
  );
});
