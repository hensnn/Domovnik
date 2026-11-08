import { useCallback, useSyncExternalStore } from "react";

/** Událost, kterou Chrome / Edge pošle, když jde aplikaci nainstalovat (není ve standardních typech). */
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let deferred: BeforeInstallPromptEvent | null = null;
let installedNow = false;
let version = 0;
const listeners = new Set<() => void>();
const notify = () => {
  version++;
  listeners.forEach((l) => l());
};

// Událost přijde brzy po načtení (a jen jednou), proto se zachytává už při importu modulu,
// ne až po vykreslení komponenty.
if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e as BeforeInstallPromptEvent;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    installedNow = true;
    notify();
  });
}

/** Aplikace už běží jako nainstalovaná (vlastní okno bez lišty prohlížeče). */
export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  const nav = navigator as Navigator & { standalone?: boolean };
  return (
    !!window.matchMedia?.("(display-mode: standalone)").matches ||
    nav.standalone === true ||
    installedNow
  );
}

export function isIOS(): boolean {
  if (typeof navigator === "undefined") return false;
  // iPadOS 13+ se hlásí jako Mac, ale má dotykovou obrazovku
  return (
    /iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

export type InstallResult = "accepted" | "dismissed" | "unavailable";

export interface InstallState {
  /** Prohlížeč umí nabídnout instalaci jedním klepnutím (Android Chrome, desktop Chrome / Edge). */
  canPrompt: boolean;
  /** Už běží jako nainstalovaná aplikace. */
  installed: boolean;
  ios: boolean;
  /** HTTPS (nebo localhost): bez něj prohlížeč instalaci nenabídne. */
  secure: boolean;
  prompt: () => Promise<InstallResult>;
}

export function useInstall(): InstallState {
  useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => version,
    () => 0,
  );
  const prompt = useCallback(async (): Promise<InstallResult> => {
    const ev = deferred;
    if (!ev) return "unavailable";
    deferred = null; // událost jde použít jen jednou
    notify();
    await ev.prompt();
    const { outcome } = await ev.userChoice;
    if (outcome === "accepted") installedNow = true;
    notify();
    return outcome;
  }, []);
  return {
    canPrompt: deferred !== null,
    installed: isStandalone(),
    ios: isIOS(),
    secure: typeof window === "undefined" ? true : window.isSecureContext,
    prompt,
  };
}

const HIDDEN_KEY = "install.hiddenAt";

/** Uživatel nabídku instalace skryl před méně než `days` dny. */
export function bannerHiddenRecently(days: number): boolean {
  try {
    const at = Number(localStorage.getItem(HIDDEN_KEY) ?? 0);
    return Date.now() - at < days * 24 * 3600 * 1000;
  } catch {
    return false;
  }
}

export function hideBanner() {
  try {
    localStorage.setItem(HIDDEN_KEY, String(Date.now()));
  } catch {
    /* soukromý režim – nabídka se prostě ukáže znovu */
  }
}

/** Jen pro testy: vrátí modul do výchozího stavu. */
export function __resetInstallForTests() {
  deferred = null;
  installedNow = false;
  notify();
}
