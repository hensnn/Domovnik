import { useCallback, useState } from "react";

/** useState zálohovaný v localStorage (např. viditelné sloupce tabulky). */
export function useStoredState<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (v: T) => {
      setValue(v);
      try {
        localStorage.setItem(key, JSON.stringify(v));
      } catch {
        /* soukromý režim apod. – ignoruj */
      }
    },
    [key],
  );
  return [value, set];
}
