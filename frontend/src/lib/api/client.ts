import { validOptimizeResponse, validRouteResponse } from "./validation";
import type {
  ApiErrorResponse,
  HealthResponse,
  OptimizeRequest,
  OptimizeResponse,
  RouteRequest,
  RouteResponse,
} from "@/types/api";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/+$/, "");
export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
    public details: ApiErrorResponse["error"]["details"] = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
  timeoutMs = 30_000,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timer = setTimeout(abort, timeoutMs);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      signal: controller.signal,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const envelope = body as Partial<ApiErrorResponse> | null;
      throw new ApiError(
        envelope?.error?.message ||
          `The API returned HTTP ${response.status}. Try again.`,
        envelope?.error?.code || "http_error",
        response.status,
        envelope?.error?.details ?? null,
      );
    }
    if (!body || typeof body !== "object")
      throw new ApiError(
        "The API returned an unreadable response.",
        "invalid_response",
        response.status,
      );
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (controller.signal.aborted)
      throw new ApiError(
        options.signal?.aborted
          ? "Request cancelled."
          : "The API took too long to respond. Please try again.",
        options.signal?.aborted ? "cancelled" : "client_timeout",
        0,
      );
    throw new ApiError(
      "Cannot reach the RouteFuel API. Check that Django is running and the API address and CORS settings are correct.",
      "network_error",
      0,
    );
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", abort);
  }
}
export async function getHealth(signal?: AbortSignal) {
  const health = await request<HealthResponse>(
    "/api/v1/health/",
    { signal },
    5_000,
  );
  if (health.status !== "ok" || health.service !== "routefuel-api")
    throw new ApiError("Unexpected health response.", "invalid_response", 200);
  return health;
}
export async function optimizeRoute(
  body: OptimizeRequest,
  signal?: AbortSignal,
) {
  const result = await request<OptimizeResponse>("/api/v1/routes/optimize/", {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });
  if (!validOptimizeResponse(result))
    throw new ApiError(
      "The API returned an invalid route or fuel plan. Your last valid plan is unchanged. Try again or inspect the API response.",
      "invalid_response",
      200,
    );
  return result;
}
export async function getRoute(body: RouteRequest, signal?: AbortSignal) {
  const result = await request<RouteResponse>("/api/v1/routes/", {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });
  if (!validRouteResponse(result))
    throw new ApiError(
      "The API returned invalid route geometry.",
      "invalid_response",
      200,
    );
  return result;
}
