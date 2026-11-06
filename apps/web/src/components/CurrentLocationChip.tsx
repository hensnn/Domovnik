import { MapPin, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useLocations } from "../api/hooks";
import { useCurrentLocation } from "../lib/currentLocation";

/** Chip „Jsem tady: …“ v hlavičce (nastavuje se naskenováním štítku umístění). */
export default function CurrentLocationChip() {
  const { t } = useTranslation();
  const [id, setId] = useCurrentLocation();
  const { data } = useLocations();
  const loc = id ? data?.find((l) => l.id === id) : undefined;
  // umístění už neexistuje / je archivované → nezobrazuj (hodnota se nemaže, dokud data nejsou)
  if (!id || (data && !loc)) return null;
  return (
    <span className="flex max-w-[11rem] shrink-0 items-center gap-1 rounded-full bg-brand-50 py-1 pl-2 pr-1 text-xs font-medium text-brand-700 md:max-w-xs dark:bg-brand-700/20 dark:text-brand-100">
      <MapPin className="size-3.5 shrink-0" aria-hidden />
      <Link
        to={`/locations/${id}`}
        className="truncate"
        title={loc?.full_name ?? undefined}
        aria-label={t("scan.hereChip", { name: loc?.name ?? "…" })}
      >
        {loc?.name ?? "…"}
      </Link>
      <button
        type="button"
        onClick={() => setId(null)}
        aria-label={t("scan.hereClear")}
        title={t("scan.hereClear")}
        className="grid size-5 shrink-0 place-items-center rounded-full hover:bg-brand-100 dark:hover:bg-brand-700/40"
      >
        <X className="size-3" />
      </button>
    </span>
  );
}
