import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { __resetInstallForTests } from "../lib/install";
import { InstallBanner, InstallButton } from "./InstallApp";

function fireInstallPrompt(outcome: "accepted" | "dismissed" = "accepted") {
  const prompt = vi.fn().mockResolvedValue(undefined);
  const ev = Object.assign(new Event("beforeinstallprompt", { cancelable: true }), {
    prompt,
    userChoice: Promise.resolve({ outcome }),
  });
  act(() => {
    window.dispatchEvent(ev);
  });
  return { ev, prompt };
}

const setUA = (ua: string) =>
  Object.defineProperty(window.navigator, "userAgent", { value: ua, configurable: true });
const ANDROID = "Mozilla/5.0 (Linux; Android 14) Chrome/130 Mobile Safari/537.36";
const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1";

beforeEach(() => {
  localStorage.clear();
  setUA(ANDROID);
  window.matchMedia = ((q: string) => ({ matches: false, media: q })) as never;
  Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
  __resetInstallForTests();
});
afterEach(() => vi.restoreAllMocks());

describe("InstallButton", () => {
  it("při nabídce od prohlížeče spustí instalaci jedním klepnutím", async () => {
    render(<InstallButton />);
    const { ev, prompt } = fireInstallPrompt();
    expect(ev.defaultPrevented).toBe(true); // prohlížeč nesmí ukázat vlastní lištu
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Nainstalovat aplikaci" }));
    });
    expect(prompt).toHaveBeenCalledTimes(1);
  });

  it("bez nabídky od prohlížeče ukáže návod, na HTTP upozorní na chybějící HTTPS", () => {
    Object.defineProperty(window, "isSecureContext", { value: false, configurable: true });
    render(<InstallButton />);
    fireEvent.click(screen.getByRole("button", { name: "Nainstalovat aplikaci" }));
    expect(screen.getByText("Android (Chrome)")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("HTTPS");
  });

  it("na iPhonu ukáže postup přes Sdílet → Přidat na plochu", () => {
    setUA(IPHONE);
    render(<InstallButton />);
    fireEvent.click(screen.getByRole("button", { name: "Nainstalovat aplikaci" }));
    expect(screen.getByText("iPhone / iPad (Safari)")).toBeInTheDocument();
    expect(screen.getByText(/Přidat na plochu/)).toBeInTheDocument();
    expect(screen.queryByText("Android (Chrome)")).not.toBeInTheDocument();
  });

  it("nainstalovaná aplikace tlačítko neukazuje", () => {
    window.matchMedia = ((q: string) => ({ matches: q.includes("standalone") })) as never;
    render(<InstallButton />);
    expect(screen.queryByRole("button", { name: "Nainstalovat aplikaci" })).not.toBeInTheDocument();
  });

  it("po události appinstalled zmizí", () => {
    render(<InstallButton />);
    expect(screen.getByRole("button", { name: "Nainstalovat aplikaci" })).toBeInTheDocument();
    act(() => {
      window.dispatchEvent(new Event("appinstalled"));
    });
    expect(screen.queryByRole("button", { name: "Nainstalovat aplikaci" })).not.toBeInTheDocument();
  });
});

describe("InstallBanner", () => {
  it("na Androidu se ukáže, až když prohlížeč nabídne instalaci", async () => {
    render(<InstallBanner />);
    expect(screen.queryByRole("region", { name: "Instalace aplikace" })).not.toBeInTheDocument();
    const { prompt } = fireInstallPrompt();
    expect(screen.getByRole("region", { name: "Instalace aplikace" })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Nainstalovat" }));
    });
    expect(prompt).toHaveBeenCalled();
  });

  it("na iPhonu se ukáže hned a vede na návod", () => {
    setUA(IPHONE);
    render(<InstallBanner />);
    fireEvent.click(screen.getByRole("button", { name: "Jak na to" }));
    expect(screen.getByText("iPhone / iPad (Safari)")).toBeInTheDocument();
  });

  it("jde skrýt a po opětovném načtení se na 14 dní neukáže", () => {
    setUA(IPHONE);
    const first = render(<InstallBanner />);
    fireEvent.click(screen.getByRole("button", { name: "Skrýt nabídku instalace" }));
    expect(screen.queryByRole("region", { name: "Instalace aplikace" })).not.toBeInTheDocument();
    first.unmount();
    render(<InstallBanner />);
    expect(screen.queryByRole("region", { name: "Instalace aplikace" })).not.toBeInTheDocument();

    // po uplynutí 14 dnů se nabídka vrátí
    localStorage.setItem("install.hiddenAt", String(Date.now() - 15 * 24 * 3600 * 1000));
    render(<InstallBanner />);
    expect(screen.getByRole("region", { name: "Instalace aplikace" })).toBeInTheDocument();
  });
});
