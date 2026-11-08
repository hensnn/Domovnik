import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { Detection } from "../../api/types";
import type { Choice } from "../../lib/photos";
import PhotoViewer from "./PhotoViewer";

beforeAll(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});
afterEach(() => vi.clearAllMocks());

const det = (id: string, name: string, bbox: Detection["bbox"], matched = false): Detection => ({
  id,
  label: name,
  bbox,
  confidence: 0.9,
  status: "pending",
  description: `popis ${name}`,
  suggested: { name, category_path: [], tags: [], quantity: 1, unit: "ks" },
  suggested_location: null,
  matched_item: matched
    ? { id: "i1", name: "Existující", label_code: "I-1", location_path: null }
    : null,
});

const dets = [
  det("d1", "Kladivo", [0.1, 0.1, 0.2, 0.2]),
  det("d2", "Šrouby", [0.5, 0.5, 0.2, 0.2], true),
  det("d3", "Cosi", null),
];

function Harness({ onClose = () => {} }: { onClose?: () => void }) {
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [active, setActive] = useState<string | null>(null);
  return (
    <PhotoViewer
      src="/api/v1/files/f1"
      detections={dets}
      choices={choices}
      active={active}
      onSelect={setActive}
      onChoice={(id, c) => setChoices((all) => ({ ...all, [id]: c }))}
      onClose={onClose}
    />
  );
}

describe("PhotoViewer", () => {
  it("ukáže plnou fotku s rámečky jen u nálezů, které mají polohu", () => {
    render(<Harness />);
    expect(screen.getByRole("img")).toHaveAttribute("src", "/api/v1/files/f1");
    expect(screen.getByRole("button", { name: /Kladivo/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Šrouby/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Cosi/ })).not.toBeInTheDocument();
    expect(screen.getByText("Klepni na rámeček nebo použij šipky.")).toBeInTheDocument();
  });

  it("zavře se tlačítkem i klávesou Esc", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Zavřít detail fotky" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("mění přiblížení tlačítky a klávesami a vrací celou fotku", () => {
    render(<Harness />);
    expect(screen.getByText("100 %")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Přiblížit" }));
    expect(screen.getByText("140 %")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "+" });
    expect(screen.getByText("196 %")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Oddálit" }));
    expect(screen.getByText("140 %")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Celá fotka" }));
    expect(screen.getByText("100 %")).toBeInTheDocument();
    // na 100 % nejde oddálit dál
    expect(screen.getByRole("button", { name: "Oddálit" })).toBeDisabled();
  });

  it("skrývá a znovu ukazuje rámečky", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Skrýt rámečky" }));
    expect(screen.queryByRole("button", { name: /Kladivo/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zobrazit rámečky" }));
    expect(screen.getByRole("button", { name: /Kladivo/ })).toBeInTheDocument();
  });

  it("šipky přeskakují mezi nálezy s rámečkem a ukážou jejich údaje", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Další nález" }));
    expect(screen.getByText(/1\. Kladivo/)).toBeInTheDocument();
    expect(screen.getByText(/1 z 2/)).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByText(/2\. Šrouby/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Další nález" }));
    expect(screen.getByText(/1\. Kladivo/)).toBeInTheDocument(); // dokola
    fireEvent.click(screen.getByRole("button", { name: "Předchozí nález" }));
    expect(screen.getByText(/2\. Šrouby/)).toBeInTheDocument();
  });

  it("potvrzení a odmítnutí z prohlížeče se přepínají; u duplicity chybí „přijmout“", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /Kladivo/ }));
    const accept = screen.getByRole("button", { name: "Přijmout" });
    fireEvent.click(accept);
    expect(screen.getByRole("button", { name: "Přijmout" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Přijmout" }));
    expect(screen.getByRole("button", { name: "Přijmout" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    fireEvent.click(screen.getByRole("button", { name: "Zamítnout" }));
    expect(screen.getByRole("button", { name: "Zamítnout" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(screen.getByRole("button", { name: /Šrouby/ }));
    expect(screen.queryByRole("button", { name: "Přijmout" })).not.toBeInTheDocument();
    expect(screen.getByText(/Je to možná duplicita/)).toBeInTheDocument();
  });
});
