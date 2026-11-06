import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PhotoAnalysis } from "../../api/types";
import { mockFetch, problem, renderWithProviders } from "../../test/utils";
import AddFromPhotoPage from "./AddFromPhotoPage";

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ can: () => true, isAdmin: true, me: {}, logout: async () => {} }),
}));

const fileInfo = {
  id: "file1",
  kind: "photo",
  mime: "image/webp",
  size_bytes: 1000,
  width: 800,
  height: 600,
  original_name: "police.jpg",
  caption: null,
  taken_at: null,
  blurhash: null,
  thumbs_ready: true,
  created_at: "2026-01-01T00:00:00Z",
  url: "/api/v1/files/file1",
  thumb_256_url: null,
  thumb_1024_url: null,
};

const analysis: PhotoAnalysis = {
  id: "an1",
  status: "done",
  file_id: "file1",
  scene: "Police v garáži",
  detections: [
    {
      id: "d1",
      label: "Kladivo",
      bbox: [0.1, 0.1, 0.2, 0.3],
      confidence: 0.93,
      status: "pending",
      suggested: { name: "Kladivo", category_path: ["Nářadí"], tags: [], quantity: 1, unit: "ks" },
      suggested_location: { id: null, path: ["Dům", "Garáž"], reason: "u nářadí" },
      matched_item: null,
    },
    {
      id: "d2",
      label: "Šrouby",
      bbox: [0.5, 0.5, 0.2, 0.2],
      confidence: 0.62,
      status: "pending",
      suggested: {
        name: "Šrouby 4x40",
        category_path: ["Drobnosti"],
        tags: ["šrouby"],
        quantity: 50,
        unit: "ks",
      },
      suggested_location: null,
      matched_item: {
        id: "item9",
        name: "Šrouby do dřeva",
        label_code: "I-000009",
        location_path: "Dům › Dílna",
      },
    },
    {
      id: "d3",
      label: "Cosi",
      bbox: null,
      confidence: 0.3,
      status: "pending",
      suggested: { name: "Cosi", category_path: [], tags: [], quantity: 1, unit: "ks" },
      suggested_location: null,
      matched_item: null,
    },
  ],
};

const appliedChangeSet = {
  id: "cs9",
  summary: "Přidáno z fotky",
  status: "applied",
  risky: false,
  needs_ui_confirmation: false,
  reversible: true,
  operations: [
    {
      id: "o1",
      seq: 1,
      op: "create_item",
      description: "Vytvořit věc Kladivo",
      status: "applied",
      error: null,
    },
  ],
};

const baseRoutes = (): [RegExp, () => object | Response][] => [
  [/^GET \/ai\/status/, () => ({ enabled: true, configured: true })],
  [/^GET \/locations/, () => [{ id: "loc1", parent_id: null, name: "Garáž", full_name: "Garáž" }]],
  [/^GET \/categories/, () => [{ id: "cat1", parent_id: null, name: "Nářadí" }]],
  [/^GET \/tags/, () => []],
  [/^POST \/files$/, () => ({ file: fileInfo, link: null, duplicate: false })],
  [
    /^POST \/photos\/analyze$/,
    () => new Response(JSON.stringify({ id: "an1", status: "queued" }), { status: 202 }),
  ],
];

beforeEach(() => {
  localStorage.clear();
  URL.createObjectURL = vi.fn(() => "blob:test");
  URL.revokeObjectURL = vi.fn();
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

async function pickAndAnalyze() {
  const input = await screen.findByTestId("file-input");
  fireEvent.change(input, {
    target: { files: [new File(["x"], "police.jpg", { type: "image/jpeg" })] },
  });
  fireEvent.click(await screen.findByRole("button", { name: "Rozpoznat věci na fotce" }));
}

describe("AddFromPhotoPage", () => {
  it("celý tok: nahrání → analýza → revize → uložení → souhrn s Vrátit zpět", async () => {
    localStorage.setItem("domovnik.currentLocation", "loc1");
    const { calls } = mockFetch([
      ...baseRoutes(),
      [/^GET \/photos\/analyses\/an1$/, () => analysis],
      [
        /^POST \/photos\/analyses\/an1\/commit$/,
        () => ({ change_set: appliedChangeSet, created_item_ids: ["newitem1"] }),
      ],
      [
        /^GET \/items\/newitem1$/,
        () => ({ id: "newitem1", name: "Kladivo", label_code: "I-000100" }),
      ],
      [
        /^POST \/ai\/change-sets\/cs9\/undo$/,
        () => ({ ...appliedChangeSet, status: "undone", reversible: null }),
      ],
    ]);
    renderWithProviders(<AddFromPhotoPage />);

    // výchozí umístění z „Jsem tady“ jde do analýzy
    await screen.findByRole("option", { name: "Garáž" });
    fireEvent.change(screen.getByLabelText("Poznámka pro asistenta"), {
      target: { value: "police s nářadím" },
    });
    await pickAndAnalyze();

    expect(await screen.findByText("Zkontroluj nalezené věci")).toBeInTheDocument();
    const analyze = calls.find((c) => c.path === "/photos/analyze")!;
    expect(analyze.body).toEqual({
      file_id: "file1",
      context_location_id: "loc1",
      hint: "police s nářadím",
    });
    const upload = calls.find((c) => c.path === "/files")!;
    expect(upload.body).toBeInstanceOf(FormData);

    // karty a rámečky
    expect(screen.getByText("Nalezeny 3 věci")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rámeček 1: Kladivo" })).toBeInTheDocument();
    expect(screen.getByText(/Podobná věc už existuje: Šrouby do dřeva/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Uložit (0 věcí)" })).toBeDisabled();

    // přijmout vše ≥ 80 % (duplicita a nejisté zůstanou nerozhodnuté)
    fireEvent.click(screen.getByRole("button", { name: "Přijmout vše s jistotou ≥ 80 %" }));
    expect(screen.getByRole("button", { name: "Uložit (1 věc)" })).toBeEnabled();

    // duplicitu sloučím, třetí zamítnu
    const dupCard = screen.getByRole("article", { name: /Nalezená věc 2/ });
    fireEvent.click(within(dupCard).getByRole("button", { name: "Sloučit s existující" }));
    const third = screen.getByRole("article", { name: /Nalezená věc 3/ });
    fireEvent.click(within(third).getByRole("button", { name: "Zamítnout" }));
    expect(screen.getByRole("button", { name: "Uložit (2 věci)" })).toBeInTheDocument();

    // úprava názvu a množství první věci
    const first = screen.getByRole("article", { name: /Nalezená věc 1/ });
    fireEvent.click(within(first).getByRole("button", { name: "Upravit" }));
    fireEvent.change(within(first).getByLabelText("Název"), {
      target: { value: "Kladivo zámečnické" },
    });
    fireEvent.change(within(first).getByLabelText("Množství"), { target: { value: "2" } });

    fireEvent.click(screen.getByRole("button", { name: "Uložit (2 věci)" }));
    expect(await screen.findByText("Přidána 1 věc")).toBeInTheDocument();

    const commit = calls.find((c) => c.path === "/photos/analyses/an1/commit")!;
    expect(commit.body).toEqual({
      decisions: [
        {
          detection_id: "d1",
          action: "accept",
          overrides: { name: "Kladivo zámečnické", quantity: 2 },
        },
        { detection_id: "d2", action: "merge" },
        { detection_id: "d3", action: "reject" },
      ],
    });

    // odkaz na vytvořenou věc + vrácení zpět
    expect(await screen.findByRole("link", { name: "Kladivo" })).toHaveAttribute(
      "href",
      "/items/newitem1",
    );
    fireEvent.click(screen.getByRole("button", { name: "Vrátit zpět" }));
    expect(await screen.findByText("Vráceno zpět")).toBeInTheDocument();
  });

  it("počká na dokončení analýzy (queued → running → done)", async () => {
    let polls = 0;
    mockFetch([
      ...baseRoutes(),
      [
        /^GET \/photos\/analyses\/an1$/,
        () => {
          polls++;
          return polls < 2 ? { ...analysis, status: "queued", detections: [] } : analysis;
        },
      ],
    ]);
    renderWithProviders(<AddFromPhotoPage />);
    await pickAndAnalyze();
    expect(await screen.findByRole("status")).toBeInTheDocument();
    expect(
      await screen.findByText("Zkontroluj nalezené věci", undefined, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(polls).toBeGreaterThanOrEqual(2);
  });

  it("selhání analýzy ukáže chybu a nabídne zkusit znovu", async () => {
    mockFetch([
      ...baseRoutes(),
      [
        /^GET \/photos\/analyses\/an1$/,
        () => ({
          ...analysis,
          status: "failed",
          error: "Model nevrátil platnou odpověď.",
          detections: [],
        }),
      ],
    ]);
    renderWithProviders(<AddFromPhotoPage />);
    await pickAndAnalyze();
    expect(await screen.findByRole("alert")).toHaveTextContent("Model nevrátil platnou odpověď.");
    expect(screen.getByRole("button", { name: "Zkusit znovu" })).toBeInTheDocument();
  });

  it("chyba při spuštění analýzy (429) se zobrazí a zůstane výběr fotky", async () => {
    mockFetch([
      ...baseRoutes().filter(([re]) => !re.source.includes("analyze")),
      [/^POST \/photos\/analyze$/, () => problem(429, "Denní limit vyčerpán.")],
    ]);
    renderWithProviders(<AddFromPhotoPage />);
    await pickAndAnalyze();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Denní limit vyčerpán.");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Rozpoznat věci na fotce" })).toBeEnabled(),
    );
  });

  it("chyba commitu (409) se ukáže v patičce a revize zůstane", async () => {
    mockFetch([
      ...baseRoutes(),
      [/^GET \/photos\/analyses\/an1$/, () => analysis],
      [/commit$/, () => problem(409, "Analýza už byla potvrzena.")],
    ]);
    renderWithProviders(<AddFromPhotoPage />);
    await pickAndAnalyze();
    await screen.findByText("Zkontroluj nalezené věci");
    fireEvent.click(screen.getByRole("button", { name: "Přijmout vše s jistotou ≥ 80 %" }));
    fireEvent.click(screen.getByRole("button", { name: "Uložit (1 věc)" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Analýza už byla potvrzena.");
    expect(screen.getByText("Zkontroluj nalezené věci")).toBeInTheDocument();
  });

  it("klik na rámeček zvýrazní kartu a klik na kartu rámeček", async () => {
    mockFetch([...baseRoutes(), [/^GET \/photos\/analyses\/an1$/, () => analysis]]);
    renderWithProviders(<AddFromPhotoPage />);
    await pickAndAnalyze();
    const box = await screen.findByRole("button", { name: "Rámeček 2: Šrouby 4x40" });
    expect(box).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(box);
    expect(box).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("article", { name: /Nalezená věc 1/ }));
    expect(box).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Rámeček 1: Kladivo" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
