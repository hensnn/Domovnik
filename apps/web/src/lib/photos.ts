// Čistá logika revize čtení fotek (bez Reactu – snadno testovatelná).

import type {
  Category,
  Detection,
  DetectionDecision,
  DetectionOverrides,
  PhotoAnalysis,
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
