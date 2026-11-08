import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { PhotoAnalysis } from "../../api/types";
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
      suggested: { name: "Kladivo", category_path: [], tags: [], quantity: 1, unit: "ks" },
      suggested_location: null,
      matched_item: null,
    },
  ],
};

describe("ReviewScreen – zvětšení fotky", () => {
  it("tlačítko Zvětšit otevře plnou fotku a volba z detailu se projeví v seznamu", () => {
    mockFetch([]);
    renderWithProviders(
      <ReviewScreen
        analysis={analysis}
        committing={false}
        error={null}
        onCommit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zvětšit fotku" }));
    const viewer = screen.getByRole("dialog", { name: "Detail fotky" });
    expect(within(viewer).getByRole("img")).toHaveAttribute("src", "/api/v1/files/file1");

    // výběr rámečku a přijetí přímo v detailu se přenese do seznamu pod fotkou
    fireEvent.click(within(viewer).getByRole("button", { name: /Kladivo/ }));
    fireEvent.click(within(viewer).getByRole("button", { name: "Přijmout" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const card = screen.getByRole("article", { name: /Kladivo/ });
    expect(within(card).getByRole("button", { name: "Přijmout" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("klepnutí na samotný náhled fotky ji také zvětší", () => {
    mockFetch([]);
    renderWithProviders(
      <ReviewScreen
        analysis={analysis}
        committing={false}
        error={null}
        onCommit={() => {}}
        onCancel={() => {}}
      />,
    );
    fireEvent.click(screen.getByAltText("Nahraná fotka"));
    expect(screen.getByRole("dialog", { name: "Detail fotky" })).toBeInTheDocument();
  });
});
