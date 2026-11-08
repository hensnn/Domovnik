import { describe, expect, it } from "vitest";

import type { Detection } from "../api/types";
import type { ReviewState } from "./photos";
import {
  type GroupContext,
  dropOnGroup,
  effectiveOf,
  groupDetections,
  isUnnamed,
  moveDetections,
} from "./reviewGroups";

const det = (
  id: string,
  extra: Partial<Detection> & { sug?: Partial<Detection["suggested"]> } = {},
) => {
  const { sug, ...rest } = extra;
  return {
    id,
    label: id,
    bbox: null,
    confidence: 0.9,
    status: "pending",
    suggested: {
      name: id,
      category_path: ["Nářadí"],
      tags: [],
      quantity: 1,
      unit: "ks",
      ...sug,
    },
    suggested_location: { id: "garaz", path: null, full_name: "Dům › Garáž" },
    matched_item: null,
    ...rest,
  } as Detection;
};

const names: Record<string, string> = { garaz: "Dům › Garáž", dilna: "Dům › Dílna" };
const ctx = (over: Partial<GroupContext> = {}): GroupContext => ({
  choices: {},
  overrides: {},
  labels: {},
  locName: (id) => names[id],
  ...over,
});
const state = (over: Partial<ReviewState> = {}): ReviewState => ({
  choices: {},
  overrides: {},
  labels: {},
  ...over,
});

describe("isUnnamed", () => {
  it("prázdné a obecné názvy jsou nepojmenované", () => {
    for (const n of [
      "",
      "  ",
      null,
      undefined,
      "Neznámá věc",
      "neznámý předmět",
      "Věc",
      "Bez názvu",
    ])
      expect(isUnnamed(n)).toBe(true);
    for (const n of ["Kladivo", "Věcička na klíče", "Akušroubovák"])
      expect(isUnnamed(n)).toBe(false);
  });
});

describe("effectiveOf", () => {
  it("přepsané hodnoty mají přednost před návrhem a určují umístění", () => {
    const d = det("a");
    const base = effectiveOf(d, {}, {}, (id) => names[id]);
    expect(base).toMatchObject({
      name: "a",
      locationKey: "id:garaz",
      locationLabel: "Dům › Garáž",
      hasName: true,
      hasCategory: true,
      hasLocation: true,
    });
    const moved = effectiveOf(d, { location_id: "dilna", name: "" }, {}, (id) => names[id]);
    expect(moved.locationLabel).toBe("Dům › Dílna");
    expect(moved.hasName).toBe(false);
    const fresh = effectiveOf(d, { location_path: ["Dům", "Krabice"] }, {}, () => undefined);
    expect(fresh.locationKey).toBe("path:dům › krabice");
    expect(fresh.locationLabel).toBe("Dům › Krabice (nové)");
    const none = effectiveOf(det("b", { suggested_location: null }), {}, {}, () => undefined);
    expect(none.hasLocation).toBe(false);
  });
});

describe("groupDetections", () => {
  const dets = [
    det("a"),
    det("b", { sug: { category_path: [] } }),
    det("c", { suggested_location: null }),
    det("d", { sug: { name: "Neznámá věc" } }),
    det("e", { suggested_location: { id: "dilna", path: null, full_name: "Dům › Dílna" } }),
  ];

  it("co řešit: nepojmenované, bez kategorie, bez umístění, hotové (každá věc jednou)", () => {
    const g = groupDetections(dets, ctx(), "triage");
    expect(g.map((x) => [x.kind, x.ids])).toEqual([
      ["unnamed", ["d"]],
      ["nocat", ["b"]],
      ["noloc", ["c"]],
      ["done", ["a", "e"]],
    ]);
    expect(g.every((x) => x.drop === undefined)).toBe(true);
  });

  it("podle umístění: nepojmenované první, bez umístění poslední, cíl pro přetažení", () => {
    const g = groupDetections(dets, ctx(), "location");
    expect(g.map((x) => x.kind)).toEqual(["unnamed", "location", "location", "noloc"]);
    expect(g[1]).toMatchObject({ title: "Dům › Dílna", ids: ["e"] });
    expect(g[2]).toMatchObject({ title: "Dům › Garáž", ids: ["a", "b"] });
    expect(g[2].drop).toEqual({ kind: "location", label: "Dům › Garáž", locationId: "garaz" });
    expect(g[3].drop).toBeUndefined(); // do „bez umístění“ se přetahovat nedá
  });

  it("podle kategorie a podle rozhodnutí", () => {
    const cat = groupDetections(dets, ctx(), "category");
    expect(cat.map((x) => x.kind)).toEqual(["unnamed", "category", "nocat"]);
    expect(cat[1].drop).toEqual({ kind: "category", path: ["Nářadí"] });

    const dec = groupDetections(
      dets,
      ctx({ choices: { a: "accept", b: "reject", c: "accept" } }),
      "decision",
    );
    expect(dec.map((x) => [x.choice, x.ids])).toEqual([
      ["pending", ["d", "e"]],
      ["accept", ["a", "c"]],
      ["reject", ["b"]],
    ]);
  });

  it("po úpravě se věc přesune do jiné skupiny", () => {
    const fixed = groupDetections(
      dets,
      ctx({ overrides: { d: { name: "Pilník" }, b: { category_path: ["Drobnosti"] } } }),
      "triage",
    );
    expect(fixed.map((x) => x.kind)).toEqual(["noloc", "done"]);
    expect(fixed[1].ids).toEqual(["a", "b", "d", "e"]);
  });
});

describe("moveDetections / dropOnGroup", () => {
  const dets = [
    det("a"),
    det("b"),
    det("c", { matched_item: { id: "i1", name: "X", label_code: "I-1" } }),
  ];

  it("přesune do jiného existujícího umístění a nové kategorie, původní stav nechá", () => {
    const st = state();
    const r = moveDetections(dets, st, ["a", "b"], {
      categoryPath: ["Drobnosti"],
      location: { id: "dilna", label: "Dům › Dílna" },
    });
    expect(r.count).toBe(2);
    expect(r.next.overrides.a).toEqual({ category_path: ["Drobnosti"], location_id: "dilna" });
    expect(r.next.labels.b).toBe("Dům › Dílna");
    expect(st.overrides).toEqual({});
  });

  it("nové umístění se uloží jako cesta s popiskem (nové)", () => {
    const r = moveDetections(dets, state(), ["a"], {
      location: { path: ["Dům", "Krabice"], label: "Dům › Krabice" },
    });
    expect(r.next.overrides.a).toEqual({ location_path: ["Dům", "Krabice"] });
    expect(r.next.labels.a).toBe("Dům › Krabice (nové)");
  });

  it("umístění shodné s návrhem se nepřepisuje a nic se nepočítá, prázdný přesun nic neudělá", () => {
    const same = moveDetections(dets, state(), ["a"], { location: { id: "garaz", label: "x" } });
    expect(same.next.overrides.a).toEqual({}); // shodné s návrhem
    expect(moveDetections(dets, state(), ["a"], {}).count).toBe(0);
    expect(moveDetections(dets, state(), ["zzz"], { categoryPath: ["X"] }).count).toBe(0);
  });

  it("puštění na skupinu rozhodnutí: merge jen u duplicit", () => {
    const merge = dropOnGroup(dets, state(), ["a", "c"], { kind: "choice", choice: "merge" });
    expect(merge.next.choices).toEqual({ c: "merge" });
    expect(merge.count).toBe(1);
    const acc = dropOnGroup(dets, state({ choices: { a: "accept" } }), ["a", "b"], {
      kind: "choice",
      choice: "accept",
    });
    expect(acc.next.choices).toEqual({ a: "accept", b: "accept" });
    expect(acc.count).toBe(1); // a už přijato
  });

  it("puštění na skupinu umístění / kategorie používá přesun", () => {
    const loc = dropOnGroup(dets, state(), ["b"], {
      kind: "location",
      locationId: "dilna",
      label: "Dům › Dílna",
    });
    expect(loc.next.overrides.b).toEqual({ location_id: "dilna" });
    const cat = dropOnGroup(dets, state(), ["b"], { kind: "category", path: ["Elektro"] });
    expect(cat.next.overrides.b).toEqual({ category_path: ["Elektro"] });
  });
});
