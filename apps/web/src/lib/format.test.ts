import { describe, expect, it } from "vitest";

import { buildTree, flattenTree, formatQty } from "./format";

describe("formatQty", () => {
  it("formátuje celá i desetinná čísla a jednotku", () => {
    expect(formatQty("12.000", "ks")).toBe("12 ks");
    expect(formatQty("1.5", "kg")).toBe("1,5 kg");
    expect(formatQty(null)).toBe("–");
  });
});

describe("buildTree / flattenTree", () => {
  const list = [
    { id: "a", parent_id: null, name: "Dům" },
    { id: "b", parent_id: "a", name: "Garáž" },
    { id: "c", parent_id: "b", name: "Police" },
    { id: "d", parent_id: null, name: "Zahrada" },
  ];
  it("složí strom podle parent_id", () => {
    const tree = buildTree(list);
    expect(tree.map((n) => n.node.id)).toEqual(["a", "d"]);
    expect(tree[0].children[0].children[0].node.id).toBe("c");
  });
  it("zploští strom s hloubkou", () => {
    expect(flattenTree(list).map((x) => [x.node.id, x.depth])).toEqual([
      ["a", 0],
      ["b", 1],
      ["c", 2],
      ["d", 0],
    ]);
  });
});
