// Čistá logika inventury (bez Reactu) – výběr řádku po naskenování, náhled změn, filtry.

import type { InventoryLine } from "./api";

const num = (v: string | null | undefined) => (v === null || v === undefined ? null : Number(v));

export type LineFilter = "all" | "todo" | "diff";

export function matchesFilter(line: InventoryLine, filter: LineFilter): boolean {
  if (filter === "todo") return line.result === "unchecked";
  if (filter === "diff") return line.result !== "unchecked" && line.result !== "ok";
  return true;
}

/** Řádek, který se po naskenování věci má odškrtnout: nejdřív očekávaný nezkontrolovaný (přednost
 *  má ten v místě „Jsem tady“), pak jakýkoli očekávaný, nakonec už přidaný neočekávaný řádek.
 *  `null` = věc v inventuře zatím není (nabídne se její přidání). */
export function lineForScannedItem(
  lines: InventoryLine[],
  itemId: string,
  currentLocationId: string | null,
): InventoryLine | null {
  const mine = lines.filter((l) => l.item_id === itemId);
  const expected = mine.filter((l) => l.expected_qty !== null);
  const unchecked = expected.filter((l) => l.result === "unchecked");
  const pool = unchecked.length ? unchecked : expected.length ? expected : mine;
  if (pool.length === 0) return null;
  return pool.find((l) => l.location_id === currentLocationId) ?? pool[0];
}

export interface PlannedChange {
  line: InventoryLine;
  from: number;
  to: number;
}

/** Změny, které by uzavření s „Zapsat změny“ provedlo (řádky s napočítaným jiným množstvím). */
export function plannedChanges(lines: InventoryLine[]): PlannedChange[] {
  const out: PlannedChange[] = [];
  for (const line of lines) {
    const counted = num(line.counted_qty);
    if (counted === null) continue;
    const from = num(line.expected_qty) ?? 0;
    if (counted !== from) out.push({ line, from, to: counted });
  }
  return out;
}

/** Podíl zkontrolovaných řádků (0–1). */
export function progress(counts: { total: number; unchecked: number }): number {
  return counts.total === 0 ? 1 : (counts.total - counts.unchecked) / counts.total;
}

/** Nové množství po kliknutí na +/−; nikdy záporné, krok 1. */
export function stepQty(current: number, delta: number): number {
  return Math.max(0, Math.round((current + delta) * 1000) / 1000);
}
