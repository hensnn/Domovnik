import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Item } from "../../api/types";
import { mockFetch, renderWithProviders } from "../../test/utils";
import ItemForm from "./ItemForm";

const source = {
  id: "i1",
  label_code: "I-000001",
  name: "Akušroubovák",
  aliases: ["vrtačka"],
  description: "Modrý",
  notes: null,
  category_id: "c1",
  status: "stored",
  is_consumable: false,
  unit: "ks",
  min_quantity: null,
  home_location_id: null,
  brand: "Bosch",
  model: "GSR 12",
  serial_no: "SN-123",
  ean: "8591234567890",
  condition: "good",
  purchase_date: null,
  purchase_price: "2500.00",
  purchase_place: null,
  warranty_until: null,
  expires_at: null,
  est_value: null,
  tags: ["nářadí"],
  placements: [{ id: "p1", location_id: "loc1", location_path: "Dům › Garáž", quantity: "2" }],
  version: 4,
} as unknown as Item;

const routes: [RegExp, () => object][] = [
  [/^GET \/categories/, () => [{ id: "c1", parent_id: null, name: "Nářadí", full_name: "Nářadí" }]],
  [
    /^GET \/locations/,
    () => [{ id: "loc1", parent_id: null, name: "Garáž", full_name: "Dům › Garáž" }],
  ],
  [/^GET \/tags/, () => []],
];

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("ItemForm – duplikace věci", () => {
  it("předvyplní údaje z originálu, vynechá sériové číslo a EAN a uloží novou věc", async () => {
    const { calls } = mockFetch([
      ...routes,
      [/^POST \/items$/, () => ({ ...source, id: "i2", name: "Akušroubovák (kopie)" })],
    ]);
    const onDone = vi.fn();
    renderWithProviders(<ItemForm copyFrom={source} onDone={onDone} onCancel={() => {}} />);

    const name = (await screen.findByLabelText("Název")) as HTMLInputElement;
    expect(name.value).toBe("Akušroubovák (kopie)");
    expect((screen.getByLabelText("Značka") as HTMLInputElement).value).toBe("Bosch");
    expect((screen.getByLabelText("Sériové číslo") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("EAN / čárový kód") as HTMLInputElement).value).toBe("");

    fireEvent.click(screen.getByRole("button", { name: "Vytvořit" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const post = calls.find((c) => c.method === "POST" && c.path === "/items")!;
    expect(post.body).toMatchObject({
      name: "Akušroubovák (kopie)",
      brand: "Bosch",
      model: "GSR 12",
      serial_no: null,
      ean: null,
      category_id: "c1",
      tags: ["nářadí"],
      placements: [{ location_id: "loc1", quantity: 1 }],
    });
    expect(calls.some((c) => c.method === "PATCH")).toBe(false); // originál se nemění
  });
});
