import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, buildQuery, setCsrfToken } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
  setCsrfToken(null);
});

describe("buildQuery", () => {
  it("přeskočí prázdné hodnoty a opakuje pole", () => {
    expect(buildQuery({ q: "kabel", empty: "", none: undefined, tag: ["a", "b"], on: true })).toBe(
      "?q=kabel&tag=a&tag=b&on=true",
    );
    expect(buildQuery({})).toBe("");
  });
});

describe("api", () => {
  it("posílá CSRF hlavičku jen u změn a převádí problem+json na ApiError", async () => {
    setCsrfToken("tok");
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ title: "conflict", detail: "Záznam změnil někdo jiný" }), {
        status: 409,
      }),
    );
    await expect(api("POST", "/items", { body: {} })).rejects.toMatchObject({
      status: 409,
      message: "Záznam změnil někdo jiný",
      isConflict: true,
    });
    expect((spy.mock.calls[0][1]?.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok");

    spy.mockResolvedValue(new Response("{}", { status: 200 }));
    await api("GET", "/items");
    expect(
      (spy.mock.calls[1][1]?.headers as Record<string, string>)["X-CSRF-Token"],
    ).toBeUndefined();
  });

  it("vrátí undefined pro 204 a čitelnou zprávu z validační chyby 422", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));
    expect(await api("DELETE", "/items/1")).toBeUndefined();
    spy.mockResolvedValue(
      new Response(JSON.stringify({ detail: [{ loc: ["body", "name"], msg: "Field required" }] }), {
        status: 422,
      }),
    );
    const err = await api("POST", "/items", { body: {} }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe("name: Field required");
  });
});
