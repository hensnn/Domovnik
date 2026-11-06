import { describe, expect, it } from "vitest";

import type { InventoryLine, LineResult } from "./api";
import { lineForScannedItem, matchesFilter, plannedChanges, progress, stepQty } from "./logic";

function line(
  over: Partial<InventoryLine> & { item_id: string; location_id: string },
): InventoryLine {
  return {
    item_name: over.item_id,
    item_label_code: "I-000001",
    unit: "ks",
    location_name: null,
    location_path: null,
    expected_qty: "1",
    counted_qty: null,
    result: "unchecked" as LineResult,
    counted_at: null,
    diff: null,
    ...over,
  };
}

describe("lineForScannedItem", () => {
  const lines = [
    line({ item_id: "a", location_id: "x" }),
    line({ item_id: "a", location_id: "y" }),
    line({ item_id: "b", location_id: "x", result: "ok", counted_qty: "1" }),
    line({ item_id: "c", location_id: "x", expected_qty: null, result: "extra", counted_qty: "1" }),
  ];
  it("preferuje nezkontrolovaný řádek v aktuálním umístění", () => {
    expect(lineForScannedItem(lines, "a", "y")?.location_id).toBe("y");
    expect(lineForScannedItem(lines, "a", null)?.location_id).toBe("x");
  });
  it("když je vše zkontrolováno, vrátí existující řádek", () => {
    expect(lineForScannedItem(lines, "b", "x")?.result).toBe("ok");
  });
  it("věc mimo inventuru nevrací nic, už přidaná neočekávaná věc se najde", () => {
    expect(lineForScannedItem(lines, "z", "x")).toBeNull();
    expect(lineForScannedItem(lines, "c", "x")?.result).toBe("extra");
  });
});

describe("plannedChanges", () => {
  it("vrátí jen řádky s jiným napočítaným množstvím", () => {
    const changes = plannedChanges([
      line({ item_id: "a", location_id: "x", expected_qty: "50", counted_qty: "40" }),
      line({ item_id: "b", location_id: "x", expected_qty: "1", counted_qty: "1" }),
      line({ item_id: "c", location_id: "x", expected_qty: null, counted_qty: "2" }),
      line({ item_id: "d", location_id: "x" }),
    ]);
    expect(changes.map((c) => [c.line.item_id, c.from, c.to])).toEqual([
      ["a", 50, 40],
      ["c", 0, 2],
    ]);
  });
});

describe("pomocné", () => {
  it("filtry", () => {
    const todo = line({ item_id: "a", location_id: "x" });
    const missing = line({ item_id: "a", location_id: "x", result: "missing" });
    expect(matchesFilter(todo, "todo")).toBe(true);
    expect(matchesFilter(missing, "todo")).toBe(false);
    expect(matchesFilter(missing, "diff")).toBe(true);
    expect(matchesFilter(todo, "diff")).toBe(false);
    expect(matchesFilter(todo, "all")).toBe(true);
  });
  it("progress a stepQty", () => {
    expect(progress({ total: 4, unchecked: 1 })).toBe(0.75);
    expect(progress({ total: 0, unchecked: 0 })).toBe(1);
    expect(stepQty(1, -1)).toBe(0);
    expect(stepQty(0, -1)).toBe(0);
    expect(stepQty(2.5, 1)).toBe(3.5);
  });
});
