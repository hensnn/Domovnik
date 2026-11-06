// Tenký klient REST API: cookie relace + CSRF hlavička, chyby ve formátu problem+json.

let csrfToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

export class ApiError extends Error {
  status: number;
  code: string;
  extra: Record<string, unknown>;

  constructor(status: number, code: string, message: string, extra: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.extra = extra;
  }

  get isConflict() {
    return this.status === 409;
  }
}

type Params = Record<string, string | number | boolean | string[] | null | undefined>;

export function buildQuery(params?: Params): string {
  if (!params) return "";
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => usp.append(key, v));
    else usp.set(key, String(value));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export interface RequestOptions {
  params?: Params;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export async function api<T>(
  method: string,
  path: string,
  { params, body, headers, signal }: RequestOptions = {},
): Promise<T> {
  const h: Record<string, string> = { Accept: "application/json", ...headers };
  if (body !== undefined) h["Content-Type"] = "application/json";
  if (csrfToken && method !== "GET") h["X-CSRF-Token"] = csrfToken;

  const res = await fetch(`/api/v1${path}${buildQuery(params)}`, {
    method,
    headers: h,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
    signal,
  });

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? safeJson(text) : null;

  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/auth/")) onUnauthorized?.();
    const d = (data ?? {}) as Record<string, unknown>;
    let message = typeof d.detail === "string" ? d.detail : `Chyba ${res.status}`;
    if (Array.isArray(d.detail)) {
      // validační chyby FastAPI (422)
      message = (d.detail as { loc?: unknown[]; msg?: string }[])
        .map((e) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg ?? ""}`)
        .join("; ");
    }
    const code = typeof d.title === "string" ? d.title : "error";
    throw new ApiError(res.status, code, message, d);
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export const get = <T>(path: string, params?: Params, signal?: AbortSignal) =>
  api<T>("GET", path, { params, signal });
export const post = <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
  api<T>("POST", path, { body: body ?? {}, headers });
export const patch = <T>(path: string, body: unknown, headers?: Record<string, string>) =>
  api<T>("PATCH", path, { body, headers });
export const put = <T>(path: string, body: unknown) => api<T>("PUT", path, { body });
export const del = <T>(path: string, params?: Params) => api<T>("DELETE", path, { params });
