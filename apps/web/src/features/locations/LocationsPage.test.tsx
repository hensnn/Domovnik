import { fireEvent, screen, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockFetch, renderWithProviders } from "../../test/utils";
import LocationsPage from "./LocationsPage";

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ can: () => true, isAdmin: true, me: {}, logout: async () => {} }),
}));

const loc = (id: string, name: string, parent: string | null, path: string) => ({
  id,
  parent_id: parent,
  name,
  kind: "room",
  label_code: `L-${id}`,
  full_name: path,
  description: null,
  notes: null,
  is_movable: false,
  item_count: 0,
  direct_item_count: 0,
  archived_at: null,
  version: 1,
});
const locations = [
  loc("dum", "Dům", null, "Dům"),
  loc("garaz", "Garáž", "dum", "Dům › Garáž"),
  loc("regal", "Regál A", "garaz", "Dům › Garáž › Regál A"),
  loc("sklep", "Sklep", "dum", "Dům › Sklep"),
];

const routes: [RegExp, () => object][] = [
  [/^GET \/locations\?/, () => locations],
  [/^GET \/locations$/, () => locations],
  [/^GET \/items/, () => ({ items: [], total: 0, limit: 200, offset: 0 })],
  [/^GET \/ai\/status/, () => ({ enabled: true, configured: true })],
  [/^GET \/ai\/conversations/, () => []],
  [/^GET \/settings/, () => []],
  [/^GET \/.*\/files/, () => []],
];

function renderAt(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/locations" element={<LocationsPage />} />
      <Route path="/locations/:id" element={<LocationsPage />} />
    </Routes>,
    route,
  );
}

beforeEach(() => {
  localStorage.clear();
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

describe("LocationsPage – strom", () => {
  it("klepnutí na řádek rozbalí větev, další klepnutí na otevřený řádek ji sbalí", async () => {
    mockFetch(routes);
    renderAt("/locations");
    const tree = await screen.findByRole("tree");
    expect(within(tree).queryByText("Regál A")).not.toBeInTheDocument(); // Garáž je sbalená

    fireEvent.click(within(tree).getByRole("link", { name: /Garáž/ }));
    expect(await within(tree).findByText("Regál A")).toBeInTheDocument();
    expect(within(tree).getByRole("link", { name: /Garáž/ }).closest("li")).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    // jiný řádek: Garáž zůstane rozbalená
    fireEvent.click(within(tree).getByRole("link", { name: /Sklep/ }));
    expect(within(tree).getByText("Regál A")).toBeInTheDocument();

    // znovu na Garáž (už není vybraná → rozbalená zůstává), a pak podruhé → sbalí
    fireEvent.click(within(tree).getByRole("link", { name: /Garáž/ }));
    expect(within(tree).getByText("Regál A")).toBeInTheDocument();
    fireEvent.click(within(tree).getByRole("link", { name: /Garáž/ }));
    expect(within(tree).queryByText("Regál A")).not.toBeInTheDocument();
  });

  it("panel asistenta se otevře s „Jsem tady“ podle otevřeného umístění", async () => {
    mockFetch(routes);
    renderAt("/locations/garaz");
    await screen.findByRole("tree");
    fireEvent.click(screen.getByRole("button", { name: "Asistent" }));
    const select = (await screen.findByLabelText("Jsem tady:")) as HTMLSelectElement;
    await screen.findByRole("option", { name: /Garáž/ });
    expect(select.value).toBe("garaz");
    expect(localStorage.getItem("domovnik.currentLocation")).toBeNull();
  });
});
