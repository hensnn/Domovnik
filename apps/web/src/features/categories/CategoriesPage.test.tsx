import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch, renderWithProviders } from "../../test/utils";
import CategoriesPage from "./CategoriesPage";

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ can: () => true, isAdmin: true, me: {}, logout: async () => {} }),
}));

const cat = (id: string, name: string, parent: string | null, count: number) => ({
  id,
  parent_id: parent,
  name,
  full_name: name,
  slug: name.toLowerCase(),
  description: null,
  color: null,
  icon: null,
  sort_order: 0,
  item_count: count,
  direct_item_count: count,
  version: 1,
});

afterEach(() => vi.restoreAllMocks());

describe("CategoriesPage – strom", () => {
  it("klepnutí na název kategorie s podkategoriemi ji sbalí a znovu rozbalí", async () => {
    mockFetch([
      [
        /^GET \/categories/,
        () => [cat("n", "Nářadí", null, 5), cat("r", "Ruční", "n", 3), cat("e", "Elektro", "n", 2)],
      ],
      [/^GET \/tags/, () => []],
      [/^GET \/ai\/status/, () => ({ enabled: true, configured: true })],
      [/^GET \/ai\/conversations/, () => []],
      [/^GET \/settings/, () => []],
      [/^GET \/locations/, () => []],
    ]);
    renderCategories();
    const toggle = await screen.findByRole("button", { name: "Nářadí" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Ruční")).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.queryByText("Ruční")).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);
    expect(screen.getByText("Ruční")).toBeInTheDocument();
  });

  it("věci kategorie otevře odkaz s počtem; list bez podkategorií je rovnou odkaz", async () => {
    mockFetch([
      [/^GET \/categories/, () => [cat("n", "Nářadí", null, 5), cat("r", "Ruční", "n", 3)]],
      [/^GET \/tags/, () => []],
      [/^GET \/ai\/status/, () => ({ enabled: true, configured: true })],
      [/^GET \/ai\/conversations/, () => []],
      [/^GET \/settings/, () => []],
      [/^GET \/locations/, () => []],
    ]);
    renderCategories();
    const count = await screen.findByRole("link", { name: "Zobrazit věci v kategorii Nářadí" });
    expect(count).toHaveAttribute("href", "/items?category_id=n");
    expect(count).toHaveTextContent("5");
    const leaf = screen.getByRole("link", { name: /Ruční/ });
    expect(leaf).toHaveAttribute("href", "/items?category_id=r");
  });
});

function renderCategories() {
  return renderWithProviders(<CategoriesPage />);
}
