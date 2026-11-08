import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch, renderWithProviders } from "../../test/utils";
import KnowledgePage from "./KnowledgePage";

let admin = true;
vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ can: () => true, isAdmin: admin, me: {}, logout: async () => {} }),
}));

const entries = [
  {
    id: "k1",
    title: "Nářadí",
    content: "Elektrické nářadí patří do kufrů v dílně.",
    topic: "rules",
    enabled: true,
    source: "admin",
    sort_order: 0,
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    version: 3,
  },
  {
    id: "k2",
    title: "Zimní věci",
    content: "Lyže jsou ve sklepě.",
    topic: "household",
    enabled: false,
    source: "ai",
    sort_order: 0,
    created_by: null,
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    version: 1,
  },
];
const settings = [
  { key: "ai.knowledge_max_chars", value: 4000 },
  { key: "ai.knowledge_enabled", value: true },
];
const routes: [RegExp, () => object][] = [
  [/^GET \/knowledge/, () => entries],
  [/^GET \/settings/, () => settings],
];

afterEach(() => {
  admin = true;
  vi.restoreAllMocks();
});

describe("KnowledgePage", () => {
  it("admin vidí záznamy včetně návrhu od AI, který čeká na schválení", async () => {
    mockFetch(routes);
    renderWithProviders(<KnowledgePage />);
    expect(
      await screen.findByText("Elektrické nářadí patří do kufrů v dílně."),
    ).toBeInTheDocument();
    expect(screen.getByText("Navrhla AI")).toBeInTheDocument();
    expect(screen.getAllByText("Čeká na schválení").length).toBeGreaterThan(0);
    expect(screen.getByText(/1 záznam navrhla AI/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Přidat znalost" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Schválit" })).toBeInTheDocument();
  });

  it("člen jen čte: žádná tlačítka pro správu", async () => {
    admin = false;
    mockFetch(routes);
    renderWithProviders(<KnowledgePage />);
    await screen.findByText("Elektrické nářadí patří do kufrů v dílně.");
    expect(screen.queryByRole("button", { name: "Přidat znalost" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Upravit znalost/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Smazat znalost/ })).not.toBeInTheDocument();
  });

  it("filtruje podle tématu a textu", async () => {
    mockFetch(routes);
    renderWithProviders(<KnowledgePage />);
    await screen.findByText("Elektrické nářadí patří do kufrů v dílně.");
    fireEvent.click(screen.getByRole("button", { name: "Domácnost" }));
    expect(screen.queryByText("Elektrické nářadí patří do kufrů v dílně.")).not.toBeInTheDocument();
    expect(screen.getByText("Lyže jsou ve sklepě.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Vše" }));
    fireEvent.change(screen.getByLabelText("Hledat ve znalostech…"), { target: { value: "lyže" } });
    expect(screen.queryByText("Elektrické nářadí patří do kufrů v dílně.")).not.toBeInTheDocument();
    expect(screen.getByText("Lyže jsou ve sklepě.")).toBeInTheDocument();
  });

  it("přidá znalost z příkladu a pošle ji serveru", async () => {
    const { calls } = mockFetch([
      ...routes,
      [/^POST \/knowledge$/, () => ({ ...entries[0], id: "k9" })],
    ]);
    renderWithProviders(<KnowledgePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Přidat znalost" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Sezónní věci" }));
    expect(within(dialog).getByLabelText("Název")).toHaveValue("Sezónní věci");
    fireEvent.click(within(dialog).getByRole("button", { name: "Uložit" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({
      title: "Sezónní věci",
      topic: "rules",
      enabled: true,
    });
  });

  it("schválení návrhu od AI zapne záznam s If-Match", async () => {
    const { calls } = mockFetch([
      ...routes,
      [/^PATCH \/knowledge\/k2$/, () => ({ ...entries[1], enabled: true, version: 2 })],
    ]);
    renderWithProviders(<KnowledgePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Schválit" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(patch.body).toEqual({ enabled: true });
    expect(patch.headers["If-Match"]).toBe('"1"');
  });

  it("smaže znalost po potvrzení", async () => {
    const { calls } = mockFetch([
      ...routes,
      [/^DELETE \/knowledge\/k1$/, () => new Response(null, { status: 204 })],
    ]);
    renderWithProviders(<KnowledgePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Smazat znalost Nářadí" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Smazat" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });
});
