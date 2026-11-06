import { useEffect } from "react";

import { useSettings } from "../api/hooks";

/** Aplikuje uživatelská nastavení vzhledu (motiv, velká tlačítka) na <html>. */
export function useThemeSetting() {
  const settings = useSettings();
  const theme = (settings.data?.find((s) => s.key === "ui.theme")?.value as string) ?? "auto";
  const large = settings.data?.find((s) => s.key === "ui.large_buttons")?.value === true;

  useEffect(() => {
    const root = document.documentElement;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () =>
      root.classList.toggle("dark", theme === "dark" || (theme === "auto" && media.matches));
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);

  useEffect(() => {
    document.documentElement.classList.toggle("large-controls", large);
  }, [large]);
}
