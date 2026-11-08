import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { Detection, PhotoAnalysis } from "../../api/types";
import { mockFetch, renderWithProviders } from "../../test/utils";
import ReviewScreen from "./ReviewScreen";

beforeAll(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

const loc = (id: string, name: string) => ({
  id,
  parent_id: null,
  name,
  full_name: `Dům › ${name}`,
  kind: "room",
  label_code: `L-${id}`,
  item_count: 0,
  direct_item_count: 0,
  archived_at: null,
  version: 1,
});
const routes: [RegExp, () => object][] = [
  [/^GET \/locations/, () => [loc("garaz", "Garáž"), loc("dilna", "Dílna"), loc("sklep", "Sklep")]],
  [
    /^GET \/categories/,
    () => [
      { id: "c1", parent_id: null, name: "Nářadí", full_name: "Nářadí", item_count: 0 },
      { id: "c2", parent_id: null, name: "Drobnosti", full_name: "Drobnosti", item_count: 0 },
    ],
  ],
];

function det(id: string, name: string, extra: Partial<Detection> = {}, cat: string[] = ["Nářadí"]) {
  return {
    id,
    label: name,
    bbox: null,
    confidence: 0.9,
    status: "pending",
    suggested: { name, category_path: cat, tags: [], quantity: 1, unit: "ks" },
    suggested_location: { id: "garaz", path: null, full_name: "Dům › Garáž" },
    matched_item: null,
    ...extra,
  } as Detection;
}

const analysis: PhotoAnalysis = {
  id: "an1",
  status: "done",
  file_id: "f1",
  scene: null,
  detections: [
    det("d1", "Kladivo"),
    det(
      "d2",
      "Šrouby",
      { suggested_location: { id: "dilna", path: null, full_name: "Dům › Dílna" } },
      [],
    ),
    det("d3", "Neznámá věc"),
    det("d4", "Pásek", { suggested_location: null }),
  ],
};

function setup(a: PhotoAnalysis = analysis, onCommit = vi.fn()) {
  const m = mockFetch(routes);
  renderWithProviders(
    <ReviewScreen
      analysis={a}
      committing={false}
      error={null}
      onCommit={onCommit}
      onCancel={() => {}}
    />,
  );
  return { ...m, onCommit };
}

const section = (name: string) => screen.getByRole("region", { name });
const rowsIn = (name: string) =>
  within(section(name))
    .queryAllByRole("article")
    .map((a) => a.getAttribute("aria-label"));

describe("Kontrola nálezů – skupiny", () => {
  it("výchozí „Co řešit“: nepojmenované, bez kategorie, bez umístění a hotové mají vlastní skupiny", () => {
    setup();
    expect(rowsIn("Bez názvu")).toEqual([expect.stringContaining("Neznámá věc")]);
    expect(rowsIn("Bez kategorie")).toEqual([expect.stringContaining("Šrouby")]);
    expect(rowsIn("Bez umístění")).toEqual([expect.stringContaining("Pásek")]);
    expect(rowsIn("Hotové")).toEqual([expect.stringContaining("Kladivo")]);
  });

  it("přepíná seskupení podle umístění, kategorie a rozhodnutí", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Umístění" }));
    expect(rowsIn("Dům › Garáž")).toEqual([expect.stringContaining("Kladivo")]);
    expect(rowsIn("Dům › Dílna")).toEqual([expect.stringContaining("Šrouby")]);
    expect(rowsIn("Bez názvu")).toHaveLength(1); // nepojmenovaná vždy zvlášť
    expect(rowsIn("Bez umístění")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Kategorie" }));
    expect(rowsIn("Nářadí")).toEqual([
      expect.stringContaining("Kladivo"),
      expect.stringContaining("Pásek"),
    ]);
    expect(rowsIn("Bez kategorie")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Rozhodnutí" }));
    expect(rowsIn("Nerozhodnuto")).toHaveLength(4);
  });

  it("skupinu jde sbalit i rozbalit a „Sbalit vše“ sbalí všechny skupiny", () => {
    setup();
    expect(rowsIn("Hotové")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Sbalit skupinu Hotové" }));
    expect(rowsIn("Hotové")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Rozbalit skupinu Hotové" }));
    expect(rowsIn("Hotové")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Sbalit vše" }));
    expect(screen.queryAllByRole("article")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Rozbalit vše" }));
    expect(screen.queryAllByRole("article")).toHaveLength(4);
  });

  it("řádek jde sbalit a rozbalit; u dlouhého seznamu jsou řádky ze začátku sbalené", () => {
    setup();
    const row = screen.getByRole("article", { name: /Kladivo/ });
    expect(within(row).getByRole("button", { name: /Sbalit Kladivo/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    fireEvent.click(within(row).getByRole("button", { name: /Sbalit Kladivo/ }));
    expect(within(row).getByRole("button", { name: /Rozbalit Kladivo/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("oprava názvu přesune věc z „Bez názvu“ mezi hotové", () => {
    setup();
    const row = screen.getByRole("article", { name: /Neznámá věc/ });
    fireEvent.click(within(row).getByRole("button", { name: "Upravit" }));
    fireEvent.change(within(row).getByLabelText("Název"), { target: { value: "Pilník" } });
    expect(screen.queryByRole("region", { name: "Bez názvu" })).not.toBeInTheDocument();
    expect(rowsIn("Hotové")).toEqual(
      expect.arrayContaining([
        expect.stringContaining("Pilník"),
        expect.stringContaining("Kladivo"),
      ]),
    );
  });
});

describe("Kontrola nálezů – přesun", () => {
  it("dialog přesune věc do jiného umístění, skupina se podle toho změní a schválení pošle úpravu", async () => {
    const { onCommit } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Umístění" }));
    fireEvent.click(screen.getByRole("button", { name: "Přesunout Šrouby" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Změnit kategorii" })); // jen umístění
    await within(dialog).findByRole("option", { name: "Sklep" });
    fireEvent.change(within(dialog).getByLabelText("Umístění"), { target: { value: "sklep" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Přesunout" }));

    expect(await screen.findByRole("region", { name: "Dům › Sklep" })).toBeInTheDocument();
    expect(rowsIn("Dům › Sklep")).toEqual([expect.stringContaining("Šrouby")]);
    expect(screen.queryByRole("region", { name: "Dům › Dílna" })).not.toBeInTheDocument();

    fireEvent.click(
      within(screen.getByRole("article", { name: /Šrouby/ })).getByRole("button", {
        name: "Přijmout",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Uložit/ }));
    expect(onCommit.mock.calls[0][0]).toEqual([
      { detection_id: "d2", action: "accept", overrides: { location_id: "sklep" } },
    ]);
  });

  it("nové umístění se zadává cestou a dialog hlídá prázdný výběr", async () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Přesunout Pásek" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Změnit kategorii" }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Změnit umístění" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Přesunout" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Vyber, co se má změnit.");

    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Změnit umístění" }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Zadat nové umístění (cesta)" }));
    fireEvent.change(within(dialog).getByLabelText("Nové umístění (cesta)"), {
      target: { value: "Dům > Krabice A" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Přesunout" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(
      within(section("Hotové")).getAllByText(/Dům › Krabice A \(nové\)/).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByRole("region", { name: "Bez umístění" })).not.toBeInTheDocument();
  });

  it("hromadný výběr: vybrané věci jdou přijmout najednou nebo přesunout", async () => {
    setup();
    fireEvent.click(screen.getByRole("checkbox", { name: "Vybrat Kladivo" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Vybrat Pásek" }));
    const bar = screen.getByRole("region", { name: "Výběr nálezů" });
    expect(bar).toHaveTextContent("Vybrány 2 věci");
    fireEvent.click(within(bar).getByRole("button", { name: "Přijmout" }));
    for (const n of [/Kladivo/, /Pásek/]) {
      expect(
        within(screen.getByRole("article", { name: n })).getByRole("button", { name: "Přijmout" }),
      ).toHaveAttribute("aria-pressed", "true");
    }
    fireEvent.click(within(bar).getByRole("button", { name: "Zrušit výběr" }));
    expect(screen.queryByRole("region", { name: "Výběr nálezů" })).not.toBeInTheDocument();

    // výběr celé skupiny
    fireEvent.click(screen.getByRole("checkbox", { name: "Vybrat všechny ve skupině Hotové" }));
    expect(screen.getByRole("region", { name: "Výběr nálezů" })).toBeInTheDocument();
  });

  it("přetažení řádku na jinou skupinu umístění ho tam přesune", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Umístění" }));
    const dt = { setData: vi.fn(), setDragImage: vi.fn(), effectAllowed: "", dropEffect: "" };
    const handle = document.querySelector('[title="Přetáhnout Šrouby do jiné skupiny"]')!;
    fireEvent.dragStart(handle, { dataTransfer: dt });
    const target = section("Dům › Garáž");
    fireEvent.dragOver(target, { dataTransfer: dt });
    fireEvent.drop(target, { dataTransfer: dt });
    expect(rowsIn("Dům › Garáž")).toEqual(
      expect.arrayContaining([
        expect.stringContaining("Šrouby"),
        expect.stringContaining("Kladivo"),
      ]),
    );
    expect(screen.queryByRole("region", { name: "Dům › Dílna" })).not.toBeInTheDocument();
  });

  it("do skupiny „Bez umístění“ se přetahovat nedá", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Umístění" }));
    const dt = { setData: vi.fn(), setDragImage: vi.fn(), effectAllowed: "", dropEffect: "" };
    fireEvent.dragStart(document.querySelector('[title="Přetáhnout Kladivo do jiné skupiny"]')!, {
      dataTransfer: dt,
    });
    const noloc = section("Bez umístění");
    const over = fireEvent.dragOver(noloc, { dataTransfer: dt });
    expect(over).toBe(true); // události nikdo nezrušil = není to cíl pro puštění
    fireEvent.drop(noloc, { dataTransfer: dt });
    expect(rowsIn("Dům › Garáž")).toEqual([expect.stringContaining("Kladivo")]);
  });

  it("přetažení na skupinu rozhodnutí nastaví rozhodnutí", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Rozhodnutí" }));
    const dt = { setData: vi.fn(), setDragImage: vi.fn(), effectAllowed: "", dropEffect: "" };
    // do prázdné skupiny „Přijato“ nejde pustit, dokud neexistuje; přijmi nejdřív jednu věc
    fireEvent.click(
      within(screen.getByRole("article", { name: /Kladivo/ })).getByRole("button", {
        name: "Přijmout",
      }),
    );
    fireEvent.dragStart(document.querySelector('[title="Přetáhnout Pásek do jiné skupiny"]')!, {
      dataTransfer: dt,
    });
    const target = section("Přijato");
    fireEvent.dragOver(target, { dataTransfer: dt });
    fireEvent.drop(target, { dataTransfer: dt });
    expect(rowsIn("Přijato")).toEqual(
      expect.arrayContaining([
        expect.stringContaining("Kladivo"),
        expect.stringContaining("Pásek"),
      ]),
    );
  });
});
