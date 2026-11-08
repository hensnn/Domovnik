import { fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockFetch, renderWithProviders } from "../../test/utils";
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
  [/^GET \/locations/, () => []],
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
});
