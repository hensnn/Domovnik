// Skupiny a přesuny v kontrole nálezů z fotky (čistá logika bez Reactu, snadno testovatelná).

import type { Detection, DetectionOverrides } from "../api/types";
import { type Choice, type ReviewState, mergeOverrides } from "./photos";

export type GroupMode = "triage" | "location" | "category" | "decision";

/** Názvy, které nic neříkají – takovou věc je potřeba pojmenovat. */
const GENERIC_NAME =
  /^(bez názvu|neznám.*|nepojmenovan.*|neidentifikovan.*|předmět|věc|objekt|unknown|unnamed)$/i;

export const isUnnamed = (name: string | null | undefined): boolean => {
  const n = (name ?? "").trim();
  return n === "" || GENERIC_NAME.test(n);
};

const norm = (path: string[]) => path.map((p) => p.trim().toLowerCase()).join(" › ");

/** Skutečné hodnoty detekce = návrh z fotky přepsaný úpravami (ruční i od asistenta). */
export interface Effective {
  name: string;
  categoryPath: string[];
  /** stabilní klíč umístění: `id:<uuid>` nebo `path:<cesta>`; null = bez umístění */
  locationKey: string | null;
  locationLabel: string | null;
  locationId: string | null;
  locationPath: string[] | null;
  quantity: number;
  unit: string;
  hasName: boolean;
  hasCategory: boolean;
  hasLocation: boolean;
}

export function effectiveOf(
  d: Detection,
  ov: DetectionOverrides,
  labels: Record<string, string>,
  locName: (id: string) => string | undefined,
): Effective {
  const s = d.suggested;
  const name = ov.name !== undefined ? ov.name : s.name || d.label || "";
  const categoryPath = ov.category_path ?? s.category_path ?? [];
  let key: string | null = null;
  let label: string | null = null;
  let locationId: string | null = null;
  let locationPath: string[] | null = null;
  const sug = d.suggested_location;
  if (ov.location_path?.length) {
    key = `path:${norm(ov.location_path)}`;
    locationPath = ov.location_path;
    label = labels[d.id] ?? `${ov.location_path.join(" › ")} (nové)`;
  } else if (ov.location_id) {
    key = `id:${ov.location_id}`;
    locationId = ov.location_id;
    label = labels[d.id] ?? locName(ov.location_id) ?? null;
  } else if (sug?.id) {
    key = `id:${sug.id}`;
    locationId = sug.id;
    label = sug.full_name ?? sug.path?.join(" › ") ?? locName(sug.id) ?? null;
  } else if (sug?.path?.length) {
    key = `path:${norm(sug.path)}`;
    locationPath = sug.path;
    label = sug.path.join(" › ");
  }
  return {
    name,
    categoryPath,
    locationKey: key,
    locationLabel: label,
    locationId,
    locationPath,
    quantity: ov.quantity ?? s.quantity ?? 1,
    unit: ov.unit ?? s.unit ?? "ks",
    hasName: !isUnnamed(name),
    hasCategory: categoryPath.length > 0,
    hasLocation: key !== null,
  };
}

/** Kam jde skupinu pustit (přetažením položek) – co se tím položkám nastaví. */
export type DropTarget =
  | { kind: "location"; locationId?: string; locationPath?: string[]; label: string }
  | { kind: "category"; path: string[] }
  | { kind: "choice"; choice: Choice };

export type GroupKind =
  "unnamed" | "nocat" | "noloc" | "done" | "location" | "category" | "decision";

export interface Group {
  /** stabilní klíč skupiny (pro sbalení) */
  key: string;
  kind: GroupKind;
  /** popisek pro skupiny podle hodnoty; ostatní se pojmenují v UI podle `kind` / `choice` */
  title?: string;
  choice?: Choice;
  ids: string[];
  drop?: DropTarget;
}

export interface GroupContext {
  choices: Record<string, Choice>;
  overrides: Record<string, DetectionOverrides>;
  labels: Record<string, string>;
  locName: (id: string) => string | undefined;
}

const cs = (a: string, b: string) => a.localeCompare(b, "cs");

/**
 * Rozdělí detekce do skupin podle režimu. Nepojmenované věci mají vždy vlastní skupinu
 * na začátku (kromě režimu „rozhodnutí“); skupiny bez umístění / kategorie jsou na konci
 * a nejdou do nich přetahovat (potvrzení neumí hodnotu odebrat).
 */
export function groupDetections(dets: Detection[], ctx: GroupContext, mode: GroupMode): Group[] {
  const eff = new Map(
    dets.map((d) => [d.id, effectiveOf(d, ctx.overrides[d.id] ?? {}, ctx.labels, ctx.locName)]),
  );
  const out: Group[] = [];
  const push = (g: Group) => g.ids.length && out.push(g);
  const ids = (pred: (d: Detection, e: Effective) => boolean) =>
    dets.filter((d) => pred(d, eff.get(d.id)!)).map((d) => d.id);

  if (mode === "decision") {
    const order: Choice[] = ["pending", "accept", "merge", "reject"];
    for (const c of order) {
      push({
        key: `decision:${c}`,
        kind: "decision",
        choice: c,
        ids: ids((d) => (ctx.choices[d.id] ?? "pending") === c),
        drop: { kind: "choice", choice: c },
      });
    }
    return out;
  }

  push({ key: "unnamed", kind: "unnamed", ids: ids((_d, e) => !e.hasName) });
  const named = (_d: Detection, e: Effective) => e.hasName;

  if (mode === "triage") {
    push({ key: "nocat", kind: "nocat", ids: ids((d, e) => named(d, e) && !e.hasCategory) });
    push({
      key: "noloc",
      kind: "noloc",
      ids: ids((d, e) => named(d, e) && e.hasCategory && !e.hasLocation),
    });
    push({
      key: "done",
      kind: "done",
      ids: ids((d, e) => named(d, e) && e.hasCategory && e.hasLocation),
    });
    return out;
  }

  if (mode === "location") {
    const byKey = new Map<string, { title: string; ids: string[]; e: Effective }>();
    for (const d of dets) {
      const e = eff.get(d.id)!;
      if (!e.hasName || !e.hasLocation) continue;
      const k = e.locationKey!;
      const g = byKey.get(k) ?? { title: e.locationLabel ?? "?", ids: [], e };
      g.ids.push(d.id);
      byKey.set(k, g);
    }
    [...byKey.entries()]
      .sort((a, b) => cs(a[1].title, b[1].title))
      .forEach(([k, g]) =>
        push({
          key: `loc:${k}`,
          kind: "location",
          title: g.title,
          ids: g.ids,
          drop: {
            kind: "location",
            label: g.title,
            ...(g.e.locationId
              ? { locationId: g.e.locationId }
              : { locationPath: g.e.locationPath ?? [] }),
          },
        }),
      );
    push({ key: "noloc", kind: "noloc", ids: ids((d, e) => named(d, e) && !e.hasLocation) });
    return out;
  }

  // mode === "category"
  const byCat = new Map<string, { path: string[]; ids: string[] }>();
  for (const d of dets) {
    const e = eff.get(d.id)!;
    if (!e.hasName || !e.hasCategory) continue;
    const k = norm(e.categoryPath);
    const g = byCat.get(k) ?? { path: e.categoryPath, ids: [] };
    g.ids.push(d.id);
    byCat.set(k, g);
  }
  [...byCat.entries()]
    .sort((a, b) => cs(a[1].path.join(" › "), b[1].path.join(" › ")))
    .forEach(([k, g]) =>
      push({
        key: `cat:${k}`,
        kind: "category",
        title: g.path.join(" › "),
        ids: g.ids,
        drop: { kind: "category", path: g.path },
      }),
    );
  push({ key: "nocat", kind: "nocat", ids: ids((d, e) => named(d, e) && !e.hasCategory) });
  return out;
}

/** Co se u vybraných detekcí změní (přesun do jiné kategorie a / nebo umístění). */
export interface Move {
  categoryPath?: string[];
  location?: { id?: string; path?: string[]; label: string };
}

/**
 * Přesune detekce: nastaví kategorii a / nebo umístění přes přepsané hodnoty. Původní stav
 * se nemění. Vrací nový stav a počet dotčených detekcí.
 */
export function moveDetections(
  dets: Detection[],
  state: ReviewState,
  ids: string[],
  move: Move,
): { next: ReviewState; count: number } {
  const byId = new Map(dets.map((d) => [d.id, d]));
  const next: ReviewState = {
    choices: { ...state.choices },
    overrides: { ...state.overrides },
    labels: { ...state.labels },
  };
  let count = 0;
  for (const id of ids) {
    const d = byId.get(id);
    if (!d) continue;
    const patch: DetectionOverrides = {};
    if (move.categoryPath?.length) patch.category_path = move.categoryPath;
    if (move.location?.id) {
      patch.location_id = move.location.id;
      next.labels[id] = move.location.label;
    } else if (move.location?.path?.length) {
      patch.location_path = move.location.path;
      next.labels[id] = `${move.location.label} (nové)`;
    }
    if (!Object.keys(patch).length) continue;
    next.overrides[id] = mergeOverrides(d, next.overrides[id] ?? {}, patch);
    count++;
  }
  return { next, count };
}

/** Použije puštění skupiny: umístění / kategorie přes přesun, rozhodnutí přímo (merge jen u duplicit). */
export function dropOnGroup(
  dets: Detection[],
  state: ReviewState,
  ids: string[],
  target: DropTarget,
): { next: ReviewState; count: number } {
  if (target.kind === "location") {
    return moveDetections(dets, state, ids, {
      location: {
        id: target.locationId,
        path: target.locationPath,
        label: target.label.replace(/ \(nové\)$/, ""),
      },
    });
  }
  if (target.kind === "category") {
    return moveDetections(dets, state, ids, { categoryPath: target.path });
  }
  const dup = new Set(dets.filter((d) => d.matched_item).map((d) => d.id));
  const next: ReviewState = { ...state, choices: { ...state.choices } };
  let count = 0;
  for (const id of ids) {
    if (target.choice === "merge" && !dup.has(id)) continue;
    if (next.choices[id] !== target.choice) count++;
    next.choices[id] = target.choice;
  }
  return { next, count };
}
