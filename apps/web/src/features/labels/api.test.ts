import { describe, expect, it } from "vitest";

import { MAX_LABELS_PER_PRINT, labelsPdfUrl, pageCount } from "./api";

describe("labelsPdfUrl", () => {
  it("sestaví adresu PDF s parametry", () => {
    const url = labelsPdfUrl({
      kind: "item",
      ids: ["a", "b"],
      format: "A4_3x8",
      start: 5,
      showPath: false,
    });
    const u = new URL(url, "http://x");
    expect(u.pathname).toBe("/api/v1/labels/pdf");
    expect(u.searchParams.get("ids")).toBe("a,b");
    expect(u.searchParams.get("start")).toBe("5");
    expect(u.searchParams.get("show_path")).toBe("false");
    expect(u.searchParams.get("format")).toBe("A4_3x8");
  });

  it("omezí počet ID", () => {
    const ids = Array.from({ length: MAX_LABELS_PER_PRINT + 50 }, (_, i) => `id${i}`);
    const url = labelsPdfUrl({ kind: "location", ids, format: "A4_2x5", start: 0, showPath: true });
    expect(new URL(url, "http://x").searchParams.get("ids")!.split(",")).toHaveLength(
      MAX_LABELS_PER_PRINT,
    );
  });
});

describe("pageCount", () => {
  it("počítá strany podle formátu a počáteční buňky", () => {
    expect(pageCount(24, "A4_3x8", 0)).toBe(1);
    expect(pageCount(24, "A4_3x8", 1)).toBe(2);
    expect(pageCount(11, "A4_2x5", 0)).toBe(2);
    expect(pageCount(1, "A4_4x12", 47)).toBe(1);
  });
});
