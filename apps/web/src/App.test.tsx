import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("App", () => {
  it("zobrazí verzi API, když je dostupné", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", version: "1.2.3" }), { status: 200 }),
    );
    renderApp();
    expect(await screen.findByText(/verze 1\.2\.3/)).toBeInTheDocument();
  });

  it("zobrazí chybu, když API neodpovídá", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    renderApp();
    expect(await screen.findByRole("alert")).toHaveTextContent("API není dostupné");
  });
});
