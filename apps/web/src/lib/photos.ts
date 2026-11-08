// Čistá logika revize čtení fotek (bez Reactu – snadno testovatelná).

import type {
  Category,
  Detection,
  DetectionDecision,
  DetectionOverrides,
  PhotoAnalysis,
  RefineDraftItem,
  RefineEdit,
} from "../api/types";

/** Hranice jistoty pro „Přijmout vše s jistotou ≥ 80 %“. */
export const ACCEPT_ALL_THRESHOLD = 0.8;

export type Choice = "pending" | "accept" | "reject" | "merge";

export function confidenceTone(confidence: number): "green" | "amber" | "red" {
  if (confidence >= 0.8) return "green";
  if (confidence >= 0.5) return "amber";
  return "red";
}

export const confidencePercent = (c: number) =>
  `${Math.round(Math.min(1, Math.max(0, c)) * 100)} %`;

/** Doplní chybějící pole (API ještě nemusí vracet vše) – UI pak nepadá na undefined. */
export function normalizeAnalysis(raw: PhotoAnalysis): PhotoAnalysis {
  return {
    ...raw,
    detections: (raw.detections ?? []).map(normalizeDetection),
  };
}

export function normalizeDetection(d: Detection): Detection {
  const s = d.suggested ?? ({} as Detection["suggested"]);
  const bbox =
    Array.isArray(d.bbox) && d.bbox.length === 4 && d.bbox.every((n) => Number.isFinite(n))
      ? d.bbox
      : null;
  return {
    ...d,
    bbox,
    confidence: Number.isFinite(d.confidence) ? d.confidence : 0,
    status: d.status ?? "pending",
    matched_item: d.matched_item ?? null,
    suggested_location: d.suggested_location ?? null,
    suggested: {
      ...s,
      name: s.name ?? d.label ?? "",
      category_path: s.category_path ?? [],
      tags: s.tags ?? [],
      quantity: Number.isFinite(s.quantity) && s.quantity > 0 ? s.quantity : 1,
      unit: s.unit || "ks",
    },
  };
}

/** Výchozí rozhodnutí podle stavu, který o detekci ví server. */
export function initialChoice(d: Detection): Choice {
  switch (d.status) {
    case "accepted":
    case "edited":
      return "accept";
    case "rejected":
      return "reject";
    case "merged":
      return "merge";
    default:
      return "pending";
  }
}

/** Cesta kategorie jako pole názvů od kořene. */
export function categoryPathOf(cat: Category, all: Category[]): string[] {
  const byId = new Map(all.map((c) => [c.id, c]));
  const path: string[] = [];
  const seen = new Set<string>();
  for (
    let cur: Category | undefined = cat;
    cur && !seen.has(cur.id);
    cur = cur.parent_id ? byId.get(cur.parent_id) : undefined
  ) {
    seen.add(cur.id);
    path.unshift(cur.name);
  }
  return path;
}

export const pathsEqual = (a: string[], b: string[]) =>
  a.length === b.length && a.every((x, i) => x.trim().toLowerCase() === b[i].trim().toLowerCase());

/** „Nářadí > Ruční“ → ["Nářadí", "Ruční"]. */
export function parsePath(text: string): string[] {
  return text
    .split(/[>›]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export const pathToText = (path: string[]) => path.join(" > ");

/** Souhrn rozhodnutí pro patičku revize. */
export function summarize(choices: Record<string, Choice>) {
  const values = Object.values(choices);
  return {
    save: values.filter((c) => c === "accept" || c === "merge").length,
    created: values.filter((c) => c === "accept").length,
    merged: values.filter((c) => c === "merge").length,
    rejected: values.filter((c) => c === "reject").length,
    pending: values.filter((c) => c === "pending").length,
  };
}

/** Přijme všechny nerozhodnuté detekce s dostatečnou jistotou a bez podezření na duplicitu. */
export function acceptConfident(
  detections: Detection[],
  choices: Record<string, Choice>,
  threshold = ACCEPT_ALL_THRESHOLD,
): { choices: Record<string, Choice>; accepted: number } {
  const next = { ...choices };
  let accepted = 0;
  for (const d of detections) {
    if (next[d.id] === "pending" && d.confidence >= threshold && !d.matched_item) {
      next[d.id] = "accept";
      accepted++;
    }
  }
  return { choices: next, accepted };
}

/** Rozhodnutí pro `POST …/commit` – nerozhodnuté (pending) se neposílají. */
export function buildDecisions(
  detections: Detection[],
  choices: Record<string, Choice>,
  overrides: Record<string, DetectionOverrides>,
): DetectionDecision[] {
  const out: DetectionDecision[] = [];
  for (const d of detections) {
    const c = choices[d.id];
    if (!c || c === "pending") continue;
    const decision: DetectionDecision = {
      detection_id: d.id,
      action: c === "accept" ? "accept" : c === "merge" ? "merge" : "reject",
    };
    const o = overrides[d.id];
    if (c === "accept" && o && Object.keys(o).length) decision.overrides = o;
    out.push(decision);
  }
  return out;
}

/** Dotazování na výsledek analýzy: každých ~1,5 s, nejdéle ~2 minuty. */
export const POLL_INTERVAL_MS = 1500;
export const POLL_TIMEOUT_MS = 120_000;

// --- Úpravy konceptu kontroly (ruční i od asistenta) ---------------------------------------

/**
 * Sloučí úpravu do přepsaných hodnot detekce. Hodnoty shodné s návrhem z fotky se zahodí
 * (neposílají se); volba umístění podle id a podle cesty se vzájemně vylučují.
 */
export function mergeOverrides(
  d: Detection,
  current: DetectionOverrides,
  patch: DetectionOverrides,
): DetectionOverrides {
  const merged: Record<string, unknown> = { ...current, ...patch };
  if ("location_id" in patch && !("location_path" in patch)) delete merged.location_path;
  if ("location_path" in patch && !("location_id" in patch)) delete merged.location_id;
  const s = d.suggested;
  const same: Record<string, unknown> = {
    name: s.name,
    category_path: s.category_path,
    tags: s.tags,
    brand: s.brand ?? "",
    model: s.model ?? "",
    quantity: s.quantity,
    unit: s.unit,
    notes: s.notes ?? "",
    location_id: d.suggested_location?.id ?? undefined,
  };
  for (const k of Object.keys(merged)) {
    if (JSON.stringify(merged[k]) === JSON.stringify(same[k])) delete merged[k];
  }
  return merged as DetectionOverrides;
}

/** Stav rozdělané kontroly, který asistent upravuje. */
export interface ReviewState {
  choices: Record<string, Choice>;
  overrides: Record<string, DetectionOverrides>;
  /** čitelný název vybraného umístění podle detekce (jen u úprav od asistenta) */
  labels: Record<string, string>;
}

/** Původní hodnoty jedné detekce před úpravou asistenta (pro „Vrátit“). */
export interface UndoEntry {
  detection_id: string;
  choice: Choice;
  overrides: DetectionOverrides;
  label: string | undefined;
}

/**
 * Použije návrhy asistenta na koncept. Neznámé detekce se přeskočí, `merge` projde jen u
 * duplicit. Vrací nový stav, údaje pro vrácení a id skutečně změněných detekcí.
 */
export function applyRefineEdits(
  dets: Detection[],
  state: ReviewState,
  edits: RefineEdit[],
): { next: ReviewState; undo: UndoEntry[]; touched: string[] } {
  const byId = new Map(dets.map((d) => [d.id, d]));
  const next: ReviewState = {
    choices: { ...state.choices },
    overrides: { ...state.overrides },
    labels: { ...state.labels },
  };
  const undo = new Map<string, UndoEntry>();
  const touched = new Set<string>();
  for (const e of edits) {
    const d = byId.get(e.detection_id);
    if (!d) continue;
    if (!undo.has(d.id)) {
      undo.set(d.id, {
        detection_id: d.id,
        choice: state.choices[d.id] ?? "pending",
        overrides: state.overrides[d.id] ?? {},
        label: state.labels[d.id],
      });
    }
    if (e.choice && (e.choice !== "merge" || d.matched_item)) {
      next.choices[d.id] = e.choice;
      touched.add(d.id);
    }
    if (e.changes && Object.keys(e.changes).length) {
      next.overrides[d.id] = mergeOverrides(d, next.overrides[d.id] ?? {}, e.changes);
      touched.add(d.id);
    }
    if (e.location) {
      next.labels[d.id] = e.location.is_new ? `${e.location.label} (nové)` : e.location.label;
    }
  }
  return {
    next,
    undo: [...undo.values()].filter((u) => touched.has(u.detection_id)),
    touched: [...touched],
  };
}

/** Vrátí detekce na hodnoty před úpravou asistenta. */
export function revertRefine(state: ReviewState, undo: UndoEntry[]): ReviewState {
  const next: ReviewState = {
    choices: { ...state.choices },
    overrides: { ...state.overrides },
    labels: { ...state.labels },
  };
  for (const u of undo) {
    next.choices[u.detection_id] = u.choice;
    if (Object.keys(u.overrides).length) next.overrides[u.detection_id] = u.overrides;
    else delete next.overrides[u.detection_id];
    if (u.label !== undefined) next.labels[u.detection_id] = u.label;
    else delete next.labels[u.detection_id];
  }
  return next;
}

/** Koncept pro asistenta: rozhodnutí a přepsané hodnoty všech detekcí. */
export function buildDraft(
  dets: Detection[],
  state: Pick<ReviewState, "choices" | "overrides">,
): RefineDraftItem[] {
  return dets.map((d) => {
    const o = state.overrides[d.id];
    return {
      detection_id: d.id,
      choice: state.choices[d.id] ?? "pending",
      ...(o && Object.keys(o).length ? { overrides: o } : {}),
    };
  });
}
