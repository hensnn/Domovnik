import { useCallback, useSyncExternalStore } from "react";

const KEY = "domovnik.currentLocation";
const listeners = new Set<() => void>();

function read(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setCurrentLocation(id: string | null) {
  try {
    if (id) localStorage.setItem(KEY, id);
    else localStorage.removeItem(KEY);
  } catch {
    /* ignoruj */
  }
  listeners.forEach((l) => l());
}

export function useCurrentLocation(): [string | null, (id: string | null) => void] {
  const value = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    read,
    () => null,
  );
  return [value, useCallback(setCurrentLocation, [])];
}
