import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockFetch, problem, renderWithProviders, sseResponse } from "../../test/utils";
import AssistantPage, { toolLabelKey } from "./AssistantPage";

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ can: () => true, isAdmin: true, me: {}, logout: async () => {} }),
}));

const status = {
  enabled: true,
  configured: true,
  provider: "gemini",
  model: "m",
  trust_level: "ask",
  requests_today: 3,
  requests_per_day_limit: 200,
};

const baseRoutes = (): [RegExp, () => object | Response][] => [
  [/^GET \/ai\/status/, () => status],
  [
    /^GET \/ai\/conversations\?/,
    () => [
      { id: "c0", title: "Starší dotaz", channel: "text", created_at: "2026-01-01T10:00:00Z" },
    ],
  ],
  [/^GET \/settings/, () => []],
  [
    /^GET \/locations/,
    () => [{ id: "loc1", parent_id: null, name: "Garáž", full_name: "Dům › Garáž" }],
  ],
];

beforeEach(() => {
  localStorage.clear();
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

describe("AssistantPage", () => {
  it("pošle zprávu s kontextem umístění, ukáže průběh, odpověď i kartu změn", async () => {
    const { calls } = mockFetch([
      ...baseRoutes(),
      [
        /^POST \/ai\/chat$/,
        () =>
          sseResponse([
            ["conversation", { conversation_id: "c1" }],
            ["tool_call", { name: "propose_changes", arguments: {} }],
            [
              "change_set",
              {
                change_set: {
                  id: "cs1",
                  summary: "Přesun kladiva",
                  status: "proposed",
                  risky: false,
                  needs_ui_confirmation: false,
                  reversible: null,
                  operations: [
                    {
                      id: "o1",
                      seq: 1,
                      op: "move_item",
                      description: "Přesunout Kladivo do Garáže",
                      status: "pending",
                      error: null,
                    },
                  ],
                },
              },
            ],
            ["message", { text: "Navrhuji přesun kladiva." }],
            ["done", { conversation_id: "c1", reply: "Navrhuji přesun kladiva." }],
          ]),
      ],
    ]);
    renderWithProviders(<AssistantPage />);

    await screen.findByText("Starší dotaz");
    await screen.findByRole("option", { name: "Garáž" });
    fireEvent.change(screen.getByLabelText("Jsem tady:"), { target: { value: "loc1" } });
    fireEvent.change(screen.getByLabelText("Napiš zprávu…"), {
      target: { value: "Přesuň kladivo do garáže" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Odeslat" }));

    expect(await screen.findByText("Navrhuji přesun kladiva.")).toBeInTheDocument();
    expect(await screen.findByText("Přesunout Kladivo do Garáže")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Potvrdit/ })).toBeInTheDocument();

    const chat = calls.find((c) => c.path === "/ai/chat")!;
    expect(chat.body).toEqual({
      text: "Přesuň kladivo do garáže",
      context_location_id: "loc1",
      channel: "text",
    });
    expect(localStorage.getItem("domovnik.currentLocation")).toBe("loc1");
    // další zpráva pokračuje ve stejné konverzaci
    fireEvent.change(screen.getByLabelText("Napiš zprávu…"), { target: { value: "díky" } });
    fireEvent.click(screen.getByRole("button", { name: "Odeslat" }));
    await waitFor(() => expect(calls.filter((c) => c.path === "/ai/chat")).toHaveLength(2));
    expect(
      (calls.filter((c) => c.path === "/ai/chat")[1].body as { conversation_id: string })
        .conversation_id,
    ).toBe("c1");
  });

  it("503 z API zobrazí srozumitelnou chybu", async () => {
    mockFetch([...baseRoutes(), [/^POST \/ai\/chat$/, () => problem(503, "Chybí API klíč.")]]);
    renderWithProviders(<AssistantPage />);
    fireEvent.change(await screen.findByLabelText("Napiš zprávu…"), { target: { value: "ahoj" } });
    fireEvent.click(screen.getByRole("button", { name: "Odeslat" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Asistent teď není dostupný.");
    expect(alert).toHaveTextContent("Chybí API klíč.");
  });

  it("429 zobrazí hlášku o limitu", async () => {
    mockFetch([
      ...baseRoutes(),
      [/^POST \/ai\/chat$/, () => problem(429, "Dnešní limit vyčerpán.")],
    ]);
    renderWithProviders(<AssistantPage />);
    fireEvent.change(await screen.findByLabelText("Napiš zprávu…"), { target: { value: "ahoj" } });
    fireEvent.click(screen.getByRole("button", { name: "Odeslat" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Dnešní limit vyčerpán.");
  });

  it("bez API klíče ukáže návod s odkazem do nastavení", async () => {
    mockFetch([
      ...baseRoutes().filter(([re]) => !re.source.includes("status")),
      [/^GET \/ai\/status/, () => ({ ...status, configured: false })],
    ]);
    renderWithProviders(<AssistantPage />);
    const link = await screen.findByRole("link", { name: "Otevřít nastavení" });
    expect(link).toHaveAttribute("href", "/settings?tab=ai");
  });

  it("otevře starou konverzaci a načte její zprávy; smazání ji odstraní", async () => {
    const { calls } = mockFetch([
      ...baseRoutes(),
      [
        /^GET \/ai\/conversations\/c0\/messages$/,
        () => [
          { id: 1, role: "user", content: "Kde je šroubovák?", created_at: "2026-01-01T10:00:00Z" },
          { id: 2, role: "assistant", content: "V dílně.", created_at: "2026-01-01T10:00:01Z" },
        ],
      ],
      [/^DELETE \/ai\/conversations\/c0$/, () => new Response(null, { status: 204 })],
    ]);
    renderWithProviders(<AssistantPage />);
    fireEvent.click(await screen.findByRole("button", { name: /^Starší dotaz/ }));
    expect(await screen.findByText("V dílně.")).toBeInTheDocument();
    expect(screen.getByText("Kde je šroubovák?")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Smazat konverzaci Starší dotaz" }));
    fireEvent.click(await screen.findByRole("button", { name: "Smazat" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    await waitFor(() => expect(screen.queryByText("V dílně.")).not.toBeInTheDocument());
  });

  it("bez podpory rozpoznávání řeči je mikrofon zakázaný a vysvětlený", async () => {
    mockFetch(baseRoutes());
    renderWithProviders(<AssistantPage />);
    const mic = await screen.findByRole("button", { name: /nepodporuje rozpoznávání řeči/ });
    expect(mic).toBeDisabled();
  });
});

describe("toolLabelKey", () => {
  it("známý nástroj má vlastní text, neznámý výchozí", () => {
    expect(toolLabelKey("search_items")).toBe("assistant.tool.search_items");
    expect(toolLabelKey("neco_noveho")).toBe("assistant.tool.default");
  });
});
