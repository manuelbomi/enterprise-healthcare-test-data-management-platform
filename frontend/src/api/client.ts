/**
 * Typed fetch wrapper for the control-plane REST API.
 *
 * This is the *only* place in the frontend that should call `fetch`
 * directly (see `src/api/README.md`) — every domain module in this
 * directory (`catalog.ts`, `lifecycle.ts`, `capacity.ts`, `masking.ts`,
 * `subsetting.ts`, `synthetic.ts`, `certification.ts`, `health.ts`)
 * calls through `apiGet`/`apiPost` instead of using `fetch` itself, and
 * every page/component calls through those domain modules, never
 * `fetch` directly (see `src/pages/README.md`, `src/components/README.md`).
 *
 * Base URL resolution: in local dev, `VITE_API_BASE_URL` is normally
 * left unset and requests go through the Vite dev-server proxy
 * (`vite.config.ts`'s `server.proxy["/api"]` -> `http://localhost:8000`)
 * so the browser only ever talks to one origin. Setting
 * `VITE_API_BASE_URL` (see `.env.example`) targets a control plane
 * running somewhere else (e.g. in a Playwright test that starts its own
 * server) without code changes.
 */

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

/** Distinguishes "the control plane answered, but with an error status"
 * (a real HTTP response, including the well-known 503 "artifact not
 * available yet" shape every read-only router in this platform uses —
 * see ADR-0009) from a network-level failure. Pages use this to render
 * an honest, specific message instead of a generic "something went
 * wrong."
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(`API request failed (${status}): ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      return JSON.stringify(detail);
    }
  } catch {
    // Body wasn't JSON (or was empty) -- fall through to the status text.
  }
  return response.statusText || `HTTP ${response.status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const detail = await parseErrorDetail(response);
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/** A record of query-string parameters; `undefined`/`null` values are
 * omitted (so callers can pass optional filters unconditionally). */
export type QueryParams = Record<string, string | number | boolean | undefined | null>;

function buildQuery(params?: QueryParams): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export function apiGet<T>(path: string, params?: QueryParams): Promise<T> {
  return request<T>(`${path}${buildQuery(params)}`, { method: "GET" });
}

export function apiPost<T>(path: string, body?: unknown, params?: QueryParams): Promise<T> {
  return request<T>(`${path}${buildQuery(params)}`, {
    method: "POST",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export function apiPut<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}
