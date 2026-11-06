// Tenký klient REST API: cookie relace + CSRF hlavička, chyby ve formátu problem+json.

let csrfToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
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
  /** Objekt se pošle jako JSON; FormData jako multipart (Content-Type doplní prohlížeč). */
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
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isForm) h["Content-Type"] = "application/json";
  if (csrfToken && method !== "GET") h["X-CSRF-Token"] = csrfToken;

  const res = await fetch(`/api/v1${path}${buildQuery(params)}`, {
    method,
    headers: h,
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    credentials: "same-origin",
    signal,
  });

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? safeJson(text) : null;

  if (!res.ok) throw errorFromResponse(res.status, data, path);
  return data as T;
}

/** Převede tělo chyby (problem+json) na ApiError; 401 mimo /auth/ odhlásí. */
export function errorFromResponse(status: number, data: unknown, path = ""): ApiError {
  if (status === 401 && !path.startsWith("/auth/")) onUnauthorized?.();
  const d = (data ?? {}) as Record<string, unknown>;
  let message = typeof d.detail === "string" ? d.detail : `Chyba ${status}`;
  if (Array.isArray(d.detail)) {
    // validační chyby FastAPI (422)
    message = (d.detail as { loc?: unknown[]; msg?: string }[])
      .map((e) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg ?? ""}`)
      .join("; ");
  }
  const code = typeof d.title === "string" ? d.title : "error";
  return new ApiError(status, code, message, d);
}

export function safeJson(text: string): unknown {
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
export const postForm = <T>(path: string, form: FormData, signal?: AbortSignal) =>
  api<T>("POST", path, { body: form, signal });
export const patch = <T>(path: string, body: unknown, headers?: Record<string, string>) =>
  api<T>("PATCH", path, { body, headers });
export const put = <T>(path: string, body: unknown) => api<T>("PUT", path, { body });
export const del = <T>(path: string, params?: Params) => api<T>("DELETE", path, { params });
