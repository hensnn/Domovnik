import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChangeSet } from "../../api/types";
import { mockFetch, problem, renderWithProviders } from "../../test/utils";
import ChangeSetCard from "./ChangeSetCard";

afterEach(() => vi.restoreAllMocks());

const proposed: ChangeSet = {
  id: "cs1",
  summary: "Přesun baterií",
  status: "proposed",
  risky: false,
  needs_ui_confirmation: false,
  reversible: null,
  operations: [
    {
      id: "o1",
      seq: 1,
      op: "move_item",
      description: "Přesunout Baterie AA do Kuchyně",
      status: "pending",
      error: null,
    },
    {
      id: "o2",
      seq: 2,
      op: "move_item",
      description: "Přesunout Baterie AAA do Kuchyně",
      status: "pending",
      error: null,
    },
  ],
};

describe("ChangeSetCard", () => {
  it("zobrazí diff operací a potvrdí vše; po provedení nabídne Vrátit zpět", async () => {
    const { calls } = mockFetch([
      [
        /^POST \/ai\/change-sets\/cs1\/apply$/,
        () => ({
          ...proposed,
          status: "applied",
          reversible: true,
          operations: proposed.operations.map((o) => ({ ...o, status: "applied" })),
        }),
      ],
      [
        /^POST \/ai\/change-sets\/cs1\/undo$/,
        () => ({ ...proposed, status: "undone", reversible: null }),
      ],
    ]);
    renderWithProviders(<ChangeSetCard changeSet={proposed} />);

    expect(screen.getByText("Čeká na potvrzení")).toBeInTheDocument();
    expect(screen.getByLabelText("Přesunout Baterie AA do Kuchyně")).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: /Potvrdit/ }));
    expect(await screen.findByText("Provedeno")).toBeInTheDocument();
    expect(calls[0].body).toEqual({ skip_operation_ids: [] });

    fireEvent.click(screen.getByRole("button", { name: "Vrátit zpět" }));
    expect(await screen.findByText("Vráceno zpět")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Vrátit zpět" })).not.toBeInTheDocument();
  });

  it("odškrtnutá operace se pošle jako skip_operation_ids", async () => {
    const { calls } = mockFetch([
      [
        /^POST \/ai\/change-sets\/cs1\/apply$/,
        () => ({ ...proposed, status: "partially_applied", reversible: null }),
      ],
    ]);
    renderWithProviders(<ChangeSetCard changeSet={proposed} />);
    fireEvent.click(screen.getByLabelText("Přesunout Baterie AAA do Kuchyně"));
    fireEvent.click(screen.getByRole("button", { name: "Potvrdit vybrané (1)" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toEqual({ skip_operation_ids: ["o2"] });
    expect(await screen.findByText("Provedeno částečně")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Vrátit zpět" })).toBeInTheDocument();
  });

  it("zamítnutí zavolá /reject", async () => {
    const { calls } = mockFetch([
      [/^POST \/ai\/change-sets\/cs1\/reject$/, () => ({ ...proposed, status: "rejected" })],
    ]);
    renderWithProviders(<ChangeSetCard changeSet={proposed} />);
    fireEvent.click(screen.getByRole("button", { name: "Zamítnout" }));
    expect(await screen.findByText("Zamítnuto")).toBeInTheDocument();
    expect(calls[0].path).toBe("/ai/change-sets/cs1/reject");
  });

  it("konflikt 409 ukáže srozumitelnou hlášku a nechá návrh k potvrzení", async () => {
    mockFetch([[/apply$/, () => problem(409, "Věc mezitím změnil někdo jiný.")]]);
    renderWithProviders(<ChangeSetCard changeSet={proposed} />);
    fireEvent.click(screen.getByRole("button", { name: /Potvrdit/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Data se mezitím změnila");
    expect(alert).toHaveTextContent("Věc mezitím změnil někdo jiný.");
    expect(screen.getByText("Čeká na potvrzení")).toBeInTheDocument();
  });

  it("u provedeného balíčku, který nejde vrátit, tlačítko Vrátit zpět není; chyby operací jsou vidět", () => {
    renderWithProviders(
      <ChangeSetCard
        changeSet={{
          ...proposed,
          status: "failed",
          reversible: false,
          operations: [
            { ...proposed.operations[0], status: "failed", error: "Umístění neexistuje" },
          ],
        }}
      />,
    );
    expect(screen.getByText("Selhalo")).toBeInTheDocument();
    expect(screen.getByText("Umístění neexistuje")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
