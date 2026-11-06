import { WifiOff } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useOnline } from "./useOnline";

/** Pruh nahoře, když zařízení nemá připojení: data se zobrazují z uložené kopie. */
export default function OfflineBanner() {
  const { t } = useTranslation();
  const online = useOnline();
  if (online) return null;
  return (
    <div
      role="status"
      className="flex items-center justify-center gap-2 bg-amber-100 px-3 py-1.5 text-center text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200"
    >
      <WifiOff className="size-4 shrink-0" aria-hidden /> {t("offline.banner")}
    </div>
  );
}
