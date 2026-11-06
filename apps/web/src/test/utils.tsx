import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "../components/ui";

export function renderWithProviders(ui: ReactElement, route = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

export interface RecordedCall {
  method: string;
  path: string;
  body: unknown;
  headers: Record<string, string>;
  raw: RequestInit | undefined;
}

type Handler = (call: RecordedCall) => Response | object | undefined;

/**
 * Nahradí fetch: `routes` se hledají podle „METHOD /cesta“ (regulární výraz nad `METHOD cesta?query`).
 * Objekt se vrátí jako JSON 200; neznámá cesta vrací 404.
 */
export function mockFetch(routes: [RegExp, Handler][]) {
  const calls: RecordedCall[] = [];
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input).replace(/^\/api\/v1/, "");
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = init?.body;
    if (typeof body === "string") {
      try {
        body = JSON.parse(body);
      } catch {
        /* nechej text */
      }
    }
    const call: RecordedCall = {
      method,
      path: url,
      body,
      headers: (init?.headers ?? {}) as Record<string, string>,
      raw: init,
    };
    calls.push(call);
    for (const [re, handler] of routes) {
      if (re.test(`${method} ${url}`)) {
        const res = handler(call);
        if (res instanceof Response) return res;
        return new Response(JSON.stringify(res ?? {}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
    return new Response(JSON.stringify({ detail: `nemockováno: ${method} ${url}` }), {
      status: 404,
    });
  });
  return { calls, spy };
}

export const problem = (status: number, detail: string) =>
  new Response(JSON.stringify({ title: "error", detail }), { status });

/** Odpověď SSE sestavená z dvojic [událost, data]; text může být rozsekaný na malé kousky. */
export function sseResponse(events: [string, unknown][], chunkSize = 17): Response {
  const text = events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join("");
  const enc = new TextEncoder();
  const bytes = enc.encode(text);
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (let i = 0; i < bytes.length; i += chunkSize) {
        controller.enqueue(bytes.slice(i, i + chunkSize));
      }
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}
