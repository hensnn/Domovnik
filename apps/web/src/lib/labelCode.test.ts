import { describe, expect, it } from "vitest";

import { normalizeCode, parseScannedText } from "./labelCode";

describe("parseScannedText", () => {
  it("vrací holý kód bez mezer", () => {
    expect(parseScannedText("  I-000123 \n")).toBe("I-000123");
  });
  it("vytáhne kód z URL (query i poslední segment cesty)", () => {
    expect(parseScannedText("https://dom.local/resolve?code=L-000004")).toBe("L-000004");
    expect(parseScannedText("https://dom.local/items/I-000007")).toBe("I-000007");
  });
  it("prázdný text zůstane prázdný", () => {
    expect(parseScannedText("   ")).toBe("");
  });
});

describe("normalizeCode", () => {
  it("doplní pomlčku, nuly a velká písmena", () => {
    expect(normalizeCode("i000123")).toBe("I-000123");
    expect(normalizeCode("l 4")).toBe("L-000004");
    expect(normalizeCode("I-000123")).toBe("I-000123");
  });
  it("vlastní kódy nechá, jen zvětší", () => {
    expect(normalizeCode("l-gar-a3")).toBe("L-GAR-A3");
  });
});
