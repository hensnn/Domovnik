import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockFetch, renderWithProviders, sseResponse } from "../../test/utils";
import AssistantDrawer from "./AssistantDrawer";

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ can: () => true, isAdmin: true, me: {}, logout: async () => {} }),
}));

const routes: [RegExp, () => object][] = [
  [
    /^GET \/ai\/status/,
    () => ({
      enabled: true,
      configured: true,
      provider: "gemini",
      model: "m",
      trust_level: "ask",
      requests_today: 0,
      requests_per_day_limit: 200,
    }),
  ],
  [/^GET \/ai\/conversations\?/, () => []],
  [/^GET \/settings/, () => []],
  [
    /^GET \/locations/,
    () => [
      { id: "loc1", parent_id: null, name: "Garáž", full_name: "Dům › Garáž" },
      { id: "loc2", parent_id: null, name: "Dílna", full_name: "Dům › Dílna" },
    ],
  ],
];

beforeEach(() => {
  localStorage.clear();
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

describe("AssistantDrawer", () => {
  it("je zavřený, dokud se neotevře", () => {
    mockFetch(routes);
    renderWithProviders(
      <AssistantDrawer open={false} onClose={() => {}} hint="Nápověda" examples={["Ukázka"]} />,
    );
    expect(screen.queryByText("Nápověda")).not.toBeInTheDocument();
  });

  it("ukáže nápovědu a ukázky pro dané místo a ukázka naplní pole", async () => {
    mockFetch(routes);
    renderWithProviders(
      <AssistantDrawer
        open
        onClose={() => {}}
        hint="Popiš, co se má založit."
        examples={["Vytvoř regál A se třemi policemi", "Přesuň Sklep pod Zahradu"]}
      />,
    );
    expect(await screen.findByText("Popiš, co se má založit.")).toBeInTheDocument();
    // vložený asistent nemá postranní seznam konverzací
    expect(screen.queryByLabelText("Historie")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Vytvoř regál A se třemi policemi" }));
    expect(screen.getByLabelText("Napiš nebo nadiktuj zprávu…")).toHaveValue(
      "Vytvoř regál A se třemi policemi",
    );
  });

  const here = () => screen.findByLabelText("Jsem tady:") as Promise<HTMLSelectElement>;

  it("předvyplní „Jsem tady“ umístěním otevřeným na stránce, globální hodnotu nemění", async () => {
    localStorage.setItem("domovnik.currentLocation", "loc2");
    const { calls } = mockFetch([
      ...routes,
      [/^POST \/ai\/chat$/, () => sseResponse([["done", { conversation_id: "c1", reply: "ok" }]])],
    ]);
    renderWithProviders(
      <AssistantDrawer open onClose={() => {}} hint="h" examples={[]} contextLocationId="loc1" />,
    );
    await screen.findByRole("option", { name: "Garáž" });
    expect((await here()).value).toBe("loc1");

    fireEvent.change(screen.getByLabelText("Napiš nebo nadiktuj zprávu…"), {
      target: { value: "přidej baterie" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Odeslat" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/ai/chat")).toBe(true));
    expect(calls.find((c) => c.path === "/ai/chat")!.body).toMatchObject({
      context_location_id: "loc1",
    });
    expect(localStorage.getItem("domovnik.currentLocation")).toBe("loc2"); // beze změny

    // změna v panelu je jen místní
    fireEvent.change(await here(), { target: { value: "loc2" } });
    expect((await here()).value).toBe("loc2");
  });

  it("bez otevřeného umístění (null) platí obvyklé „Jsem tady“", async () => {
    localStorage.setItem("domovnik.currentLocation", "loc2");
    mockFetch(routes);
    renderWithProviders(
      <AssistantDrawer open onClose={() => {}} hint="h" examples={[]} contextLocationId={null} />,
    );
    await screen.findByRole("option", { name: "Garáž" });
    expect((await here()).value).toBe("loc2");
  });

  it("stránka bez umístění (kategorie) používá globální „Jsem tady“ a mění ho", async () => {
    localStorage.setItem("domovnik.currentLocation", "loc2");
    mockFetch(routes);
    renderWithProviders(<AssistantDrawer open onClose={() => {}} hint="h" examples={[]} />);
    await screen.findByRole("option", { name: "Garáž" });
    expect((await here()).value).toBe("loc2");
    fireEvent.change(await here(), { target: { value: "loc1" } });
    expect(localStorage.getItem("domovnik.currentLocation")).toBe("loc1");
  });
});
