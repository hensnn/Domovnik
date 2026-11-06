import { afterEach, describe, expect, it, vi } from "vitest";

import { sseResponse } from "../test/utils";
import { ApiError, setCsrfToken } from "./client";
import { SseParser, streamChat, toChatEvent } from "./sse";
import type { ChatEvent } from "./types";

afterEach(() => {
  vi.restoreAllMocks();
  setCsrfToken(null);
});

describe("SseParser", () => {
  it("poskládá zprávu rozsekanou na kousky a ignoruje komentáře", () => {
    const p = new SseParser();
    expect(p.push(": keepalive\n\nevent: mess")).toEqual([]);
    expect(p.push('age\ndata: {"text":"Ahoj')).toEqual([]);
    expect(p.push(' světe"}\n\n')).toEqual([{ event: "message", data: '{"text":"Ahoj světe"}' }]);
  });

  it("zvládne CRLF, víc řádků data a výchozí název události", () => {
    const p = new SseParser();
    const out = p.push("data: a\r\ndata: b\r\n\r\nevent: done\r\ndata: {}\r\n\r\n");
    expect(out).toEqual([
      { event: "message", data: "a\nb" },
      { event: "done", data: "{}" },
    ]);
  });

  it("flush vrátí nedokončený poslední blok", () => {
    const p = new SseParser();
    expect(p.push('event: done\ndata: {"conversation_id":"c"}')).toEqual([]);
    expect(p.flush()).toEqual([{ event: "done", data: '{"conversation_id":"c"}' }]);
  });
});

describe("toChatEvent", () => {
  it("rozpozná známé události a ostatní zahodí", () => {
    expect(toChatEvent({ event: "tool_call", data: '{"name":"search_items"}' })).toMatchObject({
      type: "tool_call",
      name: "search_items",
    });
    expect(toChatEvent({ event: "ping", data: "{}" })).toBeNull();
    expect(toChatEvent({ event: "message", data: "není json" })).toBeNull();
  });
});

describe("streamChat", () => {
  it("pošle POST s CSRF a předá události v pořadí (i s češtinou rozsekanou uprostřed znaku)", async () => {
    setCsrfToken("tok");
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse(
        [
          ["conversation", { conversation_id: "c1" }],
          ["tool_call", { name: "search_items", arguments: { query: "kladivo" } }],
          ["message", { text: "Kladivo je v dílně – žluťoučký kůň." }],
          ["done", { conversation_id: "c1", reply: "Kladivo je v dílně – žluťoučký kůň." }],
        ],
        5,
      ),
    );
    const got: ChatEvent[] = [];
    await streamChat(
      { text: "Kde je kladivo?", context_location_id: "loc1", channel: "voice" },
      (e) => got.push(e),
    );
    expect(got.map((e) => e.type)).toEqual(["conversation", "tool_call", "message", "done"]);
    expect(got[2]).toMatchObject({ text: "Kladivo je v dílně – žluťoučký kůň." });
    const [url, init] = spy.mock.calls[0];
    expect(url).toBe("/api/v1/ai/chat");
    expect(init?.method).toBe("POST");
    expect((init?.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok");
    expect(JSON.parse(init?.body as string)).toEqual({
      text: "Kde je kladivo?",
      context_location_id: "loc1",
      channel: "voice",
    });
  });

  it("převede HTTP chybu (503) na ApiError s textem z problem+json", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ title: "unavailable", detail: "AI není nakonfigurovaná." }), {
        status: 503,
      }),
    );
    const err = await streamChat({ text: "x", channel: "text" }, () => {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 503, message: "AI není nakonfigurovaná." });
  });
});
