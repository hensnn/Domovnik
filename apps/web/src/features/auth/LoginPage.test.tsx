import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import LoginPage from "./LoginPage";

afterEach(() => vi.restoreAllMocks());

describe("LoginPage", () => {
  it("odešle přihlášení a zavolá onDone", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }));
    const onDone = vi.fn();
    render(<LoginPage onDone={onDone} />);
    const button = screen.getByRole("button", { name: "Přihlásit se" });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Uživatelské jméno"), { target: { value: "anna" } });
    fireEvent.change(screen.getByLabelText("Heslo"), { target: { value: "tajne-heslo-123" } });
    fireEvent.click(button);
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(spy.mock.calls[0][0]).toBe("/api/v1/auth/login");
  });

  it("zobrazí chybu při špatném hesle", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ title: "unauthorized", detail: "Nesprávné jméno nebo heslo." }),
        {
          status: 401,
        },
      ),
    );
    render(<LoginPage onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText("Uživatelské jméno"), { target: { value: "anna" } });
    fireEvent.change(screen.getByLabelText("Heslo"), { target: { value: "spatne" } });
    fireEvent.click(screen.getByRole("button", { name: "Přihlásit se" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nesprávné jméno nebo heslo.");
  });
});
