// Uložená kopie dat pro offline režim (service worker) a poslední známý přihlášený uživatel.

import { ApiError } from "../api/client";
import type { Me } from "../api/types";

const ME_KEY = "domovnik.me";
const API_CACHES = ["domovnik-api", "domovnik-thumbs"];

/** Smaže data uložená pro offline (po odhlášení nesmí zůstat dostupná dalšímu uživateli). */
export async function clearOfflineData(): Promise<void> {
  try {
    localStorage.removeItem(ME_KEY);
  } catch {
    /* ignoruj */
  }
  try {
    if (typeof caches === "undefined") return;
    await Promise.all(API_CACHES.map((name) => caches.delete(name)));
  } catch {
    /* ignoruj */
  }
}

/** Zapamatuje si přihlášeného uživatele (bez CSRF tokenu), aby šla aplikace otevřít offline. */
export function rememberMe(me: Me): void {
  try {
    localStorage.setItem(ME_KEY, JSON.stringify({ user: me.user, scopes: me.scopes }));
  } catch {
    /* ignoruj */
  }
}

export function recallMe(): Me | null {
  try {
    const raw = localStorage.getItem(ME_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Me>;
    if (!parsed.user || !Array.isArray(parsed.scopes)) return null;
    return { user: parsed.user, scopes: parsed.scopes, csrf_token: null };
  } catch {
    return null;
  }
}

/** Chyba spojení (fetch selhal), ne odpověď serveru. */
export function isNetworkError(err: unknown): boolean {
  return (err instanceof ApiError && err.isNetwork) || err instanceof TypeError;
}
