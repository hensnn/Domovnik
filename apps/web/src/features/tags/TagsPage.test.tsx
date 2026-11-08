import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch, problem, renderWithProviders } from "../../test/utils";
import TagsPage from "./TagsPage";

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ can: () => true, isAdmin: true, me: {}, logout: async () => {} }),
}));

const tags = [
  { id: "t1", name: "nářadí", color: "#ff8800", item_count: 4 },
  { id: "t2", name: "naradi", color: null, item_count: 1 },
  { id: "t3", name: "prázdný", color: null, item_count: 0 },
];

afterEach(() => vi.restoreAllMocks());

describe("TagsPage", () => {
  it("vypíše tagy s počty a filtruje je", async () => {
    mockFetch([[/^GET \/tags/, () => tags]]);
    renderWithProviders(<TagsPage />);
    expect(await screen.findByText("nářadí")).toBeInTheDocument();
    expect(screen.getByText("4 věci")).toBeInTheDocument();
    expect(screen.getByText("1 věc")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Hledat tag…"), { target: { value: "prazd" } });
    // filtr je bez ohledu na velikost písmen, ale s diakritikou (shoda podřetězce)
    expect(await screen.findByText("Žádný tag neodpovídá filtru.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Hledat tag…"), { target: { value: "prázd" } });
    expect(screen.getByText("prázdný")).toBeInTheDocument();
    expect(screen.queryByText("nářadí")).not.toBeInTheDocument();
  });

  it("přidá nový tag s barvou a ukáže chybu při duplicitě", async () => {
    const { calls } = mockFetch([
      [/^GET \/tags/, () => tags],
      [
        /^POST \/tags$/,
        (c) =>
          (c.body as { name: string }).name === "Nářadí"
            ? problem(409, "Tag „nářadí“ už existuje.")
            : { id: "t9", name: "zimní", color: null, item_count: 0 },
      ],
    ]);
    renderWithProviders(<TagsPage />);
    await screen.findByText("nářadí");
    fireEvent.change(screen.getByLabelText("Nový tag"), { target: { value: "Nářadí" } });
    fireEvent.click(screen.getByRole("button", { name: "Přidat tag" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("už existuje");

    fireEvent.change(screen.getByLabelText("Nový tag"), { target: { value: "zimní" } });
    fireEvent.click(screen.getByRole("button", { name: "Přidat tag" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(2));
    expect(calls.filter((c) => c.method === "POST")[1].body).toEqual({
      name: "zimní",
      color: null,
    });
  });

  it("přejmenuje tag a pošle jen změněná pole", async () => {
    const { calls } = mockFetch([
      [/^GET \/tags/, () => tags],
      [/^PATCH \/tags\/t3$/, () => ({ ...tags[2], name: "volné" })],
    ]);
    renderWithProviders(<TagsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Upravit tag prázdný" }));
    const dialog = await screen.findByRole("dialog");
    const save = within(dialog).getByRole("button", { name: "Uložit" });
    expect(save).toBeDisabled(); // beze změny nejde uložit
    fireEvent.change(within(dialog).getByLabelText("Název"), { target: { value: "volné" } });
    fireEvent.click(save);
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({ name: "volné" });
  });

  it("sloučí tag do vybraného cíle", async () => {
    const { calls } = mockFetch([
      [/^GET \/tags/, () => tags],
      [/^POST \/tags\/t2\/merge$/, () => tags[0]],
    ]);
    renderWithProviders(<TagsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Sloučit tag naradi do jiného" }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Sloučit" });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Cílový tag"), { target: { value: "t1" } });
    expect(
      within(dialog).getByText(/„naradi“ zmizí a věci budou mít „nářadí“/),
    ).toBeInTheDocument();
    fireEvent.click(confirm);
    await waitFor(() => expect(calls.some((c) => c.path === "/tags/t2/merge")).toBe(true));
    expect(calls.find((c) => c.path === "/tags/t2/merge")!.body).toEqual({ target_id: "t1" });
  });

  it("smaže nepoužité tagy po potvrzení", async () => {
    const { calls } = mockFetch([
      [/^GET \/tags/, () => tags],
      [/^DELETE \/tags\/t3$/, () => new Response(null, { status: 204 })],
    ]);
    renderWithProviders(<TagsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Smazat nepoužité \(1\)/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("prázdný")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Smazat" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual(["/tags/t3"]);
  });
});
