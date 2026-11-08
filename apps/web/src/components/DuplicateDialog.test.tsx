import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "../test/utils";
import { DuplicateDialog } from "./DuplicateDialog";

const base = {
  title: "Duplikovat umístění „Regál A“",
  sourceName: "Regál A",
  childrenLabel: "Zkopírovat i 3 podřízená umístění",
  hint: "Kopíruje se jen struktura.",
};

describe("DuplicateDialog", () => {
  it("bez zadaného názvu pošle jen volbu podřízených (název určí server)", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    renderWithProviders(
      <DuplicateDialog {...base} hasChildren onSubmit={onSubmit} onClose={onClose} />,
    );
    expect(screen.getByPlaceholderText("Regál A (kopie)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Vytvořit kopii" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ include_children: true }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("vlastní název a vypnutí kopie podřízených se odešlou", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <DuplicateDialog {...base} hasChildren onSubmit={onSubmit} onClose={() => {}} />,
    );
    fireEvent.change(screen.getByLabelText("Název kopie"), { target: { value: "  Regál B " } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Zkopírovat i 3/ }));
    fireEvent.click(screen.getByRole("button", { name: "Vytvořit kopii" }));
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({ name: "Regál B", include_children: false }),
    );
  });

  it("bez podřízených položek volbu nenabízí a posílá include_children=false", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(
      <DuplicateDialog {...base} hasChildren={false} onSubmit={onSubmit} onClose={() => {}} />,
    );
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Vytvořit kopii" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ include_children: false }));
  });

  it("chybu ze serveru ukáže a dialog zůstane otevřený", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("Umístění „Regál B“ už existuje."));
    const onClose = vi.fn();
    renderWithProviders(
      <DuplicateDialog {...base} hasChildren onSubmit={onSubmit} onClose={onClose} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Vytvořit kopii" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("už existuje");
    expect(onClose).not.toHaveBeenCalled();
  });
});
