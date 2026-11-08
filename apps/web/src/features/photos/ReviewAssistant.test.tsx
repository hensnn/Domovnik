import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { PhotoAnalysis } from "../../api/types";
import { mockFetch, problem, renderWithProviders } from "../../test/utils";
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

const analysis: PhotoAnalysis = {
  id: "an1",
  status: "done",
  file_id: "file1",
  scene: "Police",
  detections: [
    {
      id: "d1",
      label: "Šrouby",
      bbox: [0.1, 0.1, 0.2, 0.2],
      confidence: 0.9,
      status: "pending",
      suggested: { name: "Šrouby", category_path: [], tags: [], quantity: 1, unit: "ks" },
      suggested_location: null,
      matched_item: null,
    },
    {
      id: "d2",
      label: "Pásek",
      bbox: [0.5, 0.5, 0.2, 0.2],
      confidence: 0.6,
      status: "pending",
      suggested: { name: "Pásek", category_path: [], tags: [], quantity: 1, unit: "ks" },
      suggested_location: null,
      matched_item: null,
    },
  ],
};

const edits = {
  reply: "Přejmenoval jsem šrouby, přijal je a pásek dal do nové krabice.",
  edits: [
    {
      detection_id: "d1",
      index: 1,
      choice: "accept",
      changes: { name: "Šrouby 4x40", quantity: 50 },
    },
    {
      detection_id: "d2",
      index: 2,
      changes: { location_path: ["Dům", "Krabice"] },
      location: { id: null, path: ["Dům", "Krabice"], label: "Dům › Krabice", is_new: true },
    },
  ],
};

function setup(onCommit = vi.fn()) {
  const m = mockFetch([[/^POST \/photos\/analyses\/an1\/refine$/, () => edits]]);
  renderWithProviders(
    <ReviewScreen
      analysis={analysis}
      committing={false}
      error={null}
      onCommit={onCommit}
      onCancel={() => {}}
    />,
  );
  return { ...m, onCommit };
}

async function ask(text: string) {
  fireEvent.change(screen.getByLabelText("Napiš nebo nadiktuj, co upravit…"), {
    target: { value: text },
  });
  fireEvent.click(screen.getByRole("button", { name: "Odeslat" }));
}

describe("Asistent při kontrole nálezů", () => {
  it("úpravy se hned projeví v seznamu, jdou vrátit a uloží se až po závěrečném potvrzení", async () => {
    const { calls, onCommit } = setup();
    expect(screen.queryByRole("region", { name: "Asistent kontroly" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Upravit s asistentem" }));
    expect(screen.getByRole("region", { name: "Asistent kontroly" })).toBeInTheDocument();

    await ask("šrouby přejmenuj na 4x40 a pásek dej do nové krabice");
    expect(await screen.findByText(/Přejmenoval jsem šrouby/)).toBeInTheDocument();
    expect(screen.getByText("Změněno: 1, 2")).toBeInTheDocument();

    const req = calls.find((c) => c.path === "/photos/analyses/an1/refine")!;
    expect(req.body).toMatchObject({
      text: "šrouby přejmenuj na 4x40 a pásek dej do nové krabice",
      history: [],
      draft: [
        { detection_id: "d1", choice: "pending" },
        { detection_id: "d2", choice: "pending" },
      ],
    });

    // seznam ukazuje nový název, přijetí a nové umístění
    const card1 = screen.getByRole("article", { name: /Šrouby 4x40/ });
    expect(within(card1).getByRole("button", { name: "Přijmout" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(card1).getByText(/50 ks/)).toBeInTheDocument();
    const card2 = screen.getByRole("article", { name: /Pásek/ });
    expect(within(card2).getByText("Dům › Krabice (nové)")).toBeInTheDocument();
    expect(onCommit).not.toHaveBeenCalled(); // zatím nic uloženo

    // vrácení zruší úpravy asistenta
    fireEvent.click(screen.getByRole("button", { name: "Vrátit" }));
    expect(screen.getByText("Vráceno")).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: /Šrouby 4x40/ })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: /Šrouby/ })).toBeInTheDocument();

    // znovu a pak závěrečné schválení pošle přepsané hodnoty
    await ask("a teď to udělej znovu");
    await waitFor(() => expect(screen.getAllByText("Změněno: 1, 2")).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: /Uložit/ }));
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit.mock.calls[0][0]).toEqual([
      { detection_id: "d1", action: "accept", overrides: { name: "Šrouby 4x40", quantity: 50 } },
    ]); // d2 zůstal nerozhodnutý, jen má nové umístění
  });

  it("další dotaz posílá aktuální koncept a historii rozhovoru", async () => {
    const { calls } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Upravit s asistentem" }));
    await ask("první pokyn");
    await screen.findByText(/Přejmenoval jsem šrouby/);
    await ask("druhý pokyn");
    await waitFor(() =>
      expect(calls.filter((c) => c.path === "/photos/analyses/an1/refine")).toHaveLength(2),
    );
    const second = calls.filter((c) => c.path === "/photos/analyses/an1/refine")[1].body as {
      history: { role: string; text: string }[];
      draft: { detection_id: string; choice: string; overrides?: object }[];
    };
    expect(second.history.map((h) => h.role)).toEqual(["user", "assistant"]);
    expect(second.history[0].text).toBe("první pokyn");
    expect(second.draft[0]).toMatchObject({
      detection_id: "d1",
      choice: "accept",
      overrides: { name: "Šrouby 4x40", quantity: 50 },
    });
    expect(second.draft[1].overrides).toEqual({ location_path: ["Dům", "Krabice"] });
  });

  it("rychlá volba pošle hotový pokyn a chyba serveru se ukáže bez pádu", async () => {
    const m = mockFetch([
      [/^POST \/photos\/analyses\/an1\/refine$/, () => problem(503, "Chybí API klíč.")],
    ]);
    renderWithProviders(
      <ReviewScreen
        analysis={analysis}
        committing={false}
        error={null}
        onCommit={() => {}}
        onCancel={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Upravit s asistentem" }));
    fireEvent.click(screen.getByRole("button", { name: "Přijmi všechny s jistotou nad 80 %" }));
    expect(await screen.findByText(/Asistent teď není dostupný/)).toBeInTheDocument();
    expect(m.calls.some((c) => c.path === "/photos/analyses/an1/refine")).toBe(true);
    // koncept zůstal beze změny
    expect(
      within(screen.getByRole("article", { name: /Šrouby/ })).getByRole("button", {
        name: "Přijmout",
      }),
    ).toHaveAttribute("aria-pressed", "false");
  });
});
