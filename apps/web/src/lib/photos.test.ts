import { describe, expect, it } from "vitest";

import type { Category, Detection, PhotoAnalysis } from "../api/types";
import {
  type Choice,
  acceptConfident,
  buildDecisions,
  categoryPathOf,
  confidenceTone,
  initialChoice,
  normalizeAnalysis,
  parsePath,
  pathsEqual,
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
