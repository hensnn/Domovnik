import { describe, expect, it } from "vitest";

import type { Category, Detection, PhotoAnalysis, RefineEdit } from "../api/types";
import {
  type Choice,
  type ReviewState,
  acceptConfident,
  applyRefineEdits,
  buildDecisions,
  buildDraft,
  categoryPathOf,
  confidenceTone,
  initialChoice,
  mergeOverrides,
  normalizeAnalysis,
  parsePath,
  pathsEqual,
  revertRefine,
  summarize,
} from "./photos";

const det = (id: string, confidence: number, extra: Partial<Detection> = {}): Detection => ({
  id,
  label: id,
  bbox: null,
  confidence,
  status: "pending",
  suggested: { name: id, category_path: [], tags: [], quantity: 1, unit: "ks" },
  suggested_location: null,
  matched_item: null,
  ...extra,
});

describe("confidenceTone", () => {
  it("zelená od 0,8, oranžová 0,5–0,8, jinak červená", () => {
    expect(confidenceTone(0.95)).toBe("green");
    expect(confidenceTone(0.8)).toBe("green");
    expect(confidenceTone(0.79)).toBe("amber");
    expect(confidenceTone(0.5)).toBe("amber");
    expect(confidenceTone(0.49)).toBe("red");
  });
});

describe("acceptConfident", () => {
  it("přijme jen nerozhodnuté s jistotou ≥ 0,8 a bez podezření na duplicitu", () => {
    const dup = det("dup", 0.95, {
      matched_item: { id: "i", name: "Stejné", label_code: "I-1" },
    });
    const list = [det("a", 0.9), det("b", 0.6), dup, det("c", 0.99), det("r", 0.99)];
    const choices: Record<string, Choice> = {
      a: "pending",
      b: "pending",
      dup: "pending",
      c: "pending",
      r: "reject",
    };
    const res = acceptConfident(list, choices);
    expect(res.accepted).toBe(2);
    expect(res.choices).toMatchObject({
      a: "accept",
      b: "pending",
      dup: "pending",
      c: "accept",
      r: "reject",
    });
  });
});

describe("buildDecisions / summarize", () => {
  it("pošle jen rozhodnuté detekce a přepisy jen u přijatých", () => {
    const list = [det("a", 0.9), det("b", 0.9), det("c", 0.9), det("d", 0.9)];
    const choices: Record<string, Choice> = { a: "accept", b: "merge", c: "reject", d: "pending" };
    const decisions = buildDecisions(list, choices, {
      a: { name: "Nový název", quantity: 3 },
      b: { name: "ignorováno u sloučení" },
    });
    expect(decisions).toEqual([
      { detection_id: "a", action: "accept", overrides: { name: "Nový název", quantity: 3 } },
      { detection_id: "b", action: "merge" },
      { detection_id: "c", action: "reject" },
    ]);
    expect(summarize(choices)).toEqual({ save: 2, created: 1, merged: 1, rejected: 1, pending: 1 });
  });
});

describe("normalizeAnalysis", () => {
  it("doplní chybějící pole a zahodí neplatný bbox", () => {
    const raw = {
      id: "1",
      status: "done",
      file_id: "f",
      detections: [{ id: "d", label: "Kladivo", bbox: [0, 0, 1], confidence: 0.7 }],
    } as unknown as PhotoAnalysis;
    const d = normalizeAnalysis(raw).detections[0];
    expect(d.bbox).toBeNull();
    expect(d.suggested).toMatchObject({ name: "Kladivo", tags: [], quantity: 1, unit: "ks" });
    expect(d.status).toBe("pending");
    expect(
      normalizeAnalysis({ id: "1", status: "queued", file_id: "f" } as PhotoAnalysis).detections,
    ).toEqual([]);
  });

  it("stav ze serveru určí výchozí rozhodnutí", () => {
    expect(initialChoice(det("a", 1, { status: "accepted" }))).toBe("accept");
    expect(initialChoice(det("a", 1, { status: "edited" }))).toBe("accept");
    expect(initialChoice(det("a", 1, { status: "merged" }))).toBe("merge");
    expect(initialChoice(det("a", 1, { status: "rejected" }))).toBe("reject");
    expect(initialChoice(det("a", 1))).toBe("pending");
  });
});

describe("kategorie", () => {
  const cat = (id: string, name: string, parent_id: string | null) =>
    ({ id, name, parent_id }) as Category;
  const all = [cat("1", "Nářadí", null), cat("2", "Ruční", "1")];

  it("složí cestu od kořene a porovnává bez ohledu na velikost písmen", () => {
    expect(categoryPathOf(all[1], all)).toEqual(["Nářadí", "Ruční"]);
    expect(pathsEqual(["nářadí", "RUČNÍ"], ["Nářadí", "Ruční"])).toBe(true);
    expect(pathsEqual(["Nářadí"], ["Nářadí", "Ruční"])).toBe(false);
  });

  it("rozdělí zadanou cestu podle >", () => {
    expect(parsePath(" Nářadí >  Ruční > ")).toEqual(["Nářadí", "Ruční"]);
    expect(parsePath("")).toEqual([]);
  });
});

describe("mergeOverrides", () => {
  const d = det("a", 0.9, {
    suggested: { name: "Šroub", category_path: ["Nářadí"], tags: [], quantity: 1, unit: "ks" },
    suggested_location: { id: "loc1", path: null, full_name: "Garáž" },
  });
  it("zahodí hodnoty shodné s návrhem z fotky", () => {
    expect(mergeOverrides(d, {}, { name: "Šroub", quantity: 5 })).toEqual({ quantity: 5 });
    expect(mergeOverrides(d, { quantity: 5 }, { quantity: 1 })).toEqual({});
  });
  it("umístění podle id a podle cesty se vylučují", () => {
    const withPath = mergeOverrides(d, { location_id: "loc9" }, { location_path: ["Dům", "Nové"] });
    expect(withPath).toEqual({ location_path: ["Dům", "Nové"] });
    const withId = mergeOverrides(d, withPath, { location_id: "loc9" });
    expect(withId).toEqual({ location_id: "loc9" });
  });
});

describe("úpravy konceptu asistentem", () => {
  const dup = det("dup", 0.9, {
    matched_item: { id: "i1", name: "Akušroubovák", label_code: "I-1" },
  });
  const dets = [dup, det("b", 0.8), det("c", 0.5)];
  const base = (): ReviewState => ({
    choices: { dup: "pending", b: "pending", c: "pending" },
    overrides: { b: { notes: "stará" } },
    labels: {},
  });
  const edit = (id: string, extra: Partial<RefineEdit>): RefineEdit => ({
    detection_id: id,
    index: dets.findIndex((x) => x.id === id) + 1,
    changes: {},
    ...extra,
  });

  it("použije volbu a přepsané hodnoty, merge jen u duplicit", () => {
    const r = applyRefineEdits(dets, base(), [
      edit("dup", { choice: "merge" }),
      edit("b", { choice: "merge", changes: { name: "Šrouby 4x40", quantity: 50 } }),
      edit("c", { choice: "reject" }),
      edit("není", { choice: "accept" }),
    ]);
    expect(r.next.choices).toEqual({ dup: "merge", b: "pending", c: "reject" }); // b není duplicita
    expect(r.next.overrides.b).toEqual({ notes: "stará", name: "Šrouby 4x40", quantity: 50 });
    expect(r.touched.sort()).toEqual(["b", "c", "dup"]);
  });

  it("popisek umístění: nové umístění dostane příznak (nové)", () => {
    const r = applyRefineEdits(dets, base(), [
      edit("b", {
        changes: { location_path: ["Dům", "Krabice"] },
        location: { id: null, path: ["Dům", "Krabice"], label: "Dům › Krabice", is_new: true },
      }),
      edit("c", {
        changes: { location_id: "loc2" },
        location: { id: "loc2", path: ["Garáž"], label: "Garáž", is_new: false },
      }),
    ]);
    expect(r.next.labels).toEqual({ b: "Dům › Krabice (nové)", c: "Garáž" });
  });

  it("původní stav se nemění a vrácení obnoví jen dotčené detekce", () => {
    const state = base();
    const r = applyRefineEdits(dets, state, [
      edit("b", { choice: "accept", changes: { name: "Nový" } }),
      edit("c", { changes: {} }), // nic nemění → není v undo
    ]);
    expect(state.choices.b).toBe("pending");
    expect(r.undo.map((u) => u.detection_id)).toEqual(["b"]);

    // uživatel mezitím ručně upravil jinou detekci – vrácení se jí nedotkne
    const manual: ReviewState = {
      ...r.next,
      choices: { ...r.next.choices, c: "reject" },
    };
    const back = revertRefine(manual, r.undo);
    expect(back.choices).toEqual({ dup: "pending", b: "pending", c: "reject" });
    expect(back.overrides.b).toEqual({ notes: "stará" });
    expect(back.labels).toEqual({});
  });

  it("buildDraft pošle rozhodnutí všech detekcí a jen neprázdné úpravy", () => {
    expect(
      buildDraft(dets, { choices: { dup: "accept" }, overrides: { b: { notes: "x" }, c: {} } }),
    ).toEqual([
      { detection_id: "dup", choice: "accept" },
      { detection_id: "b", choice: "pending", overrides: { notes: "x" } },
      { detection_id: "c", choice: "pending" },
    ]);
  });
});
