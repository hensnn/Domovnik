import { useRegisterSW } from "virtual:pwa-register/react";
import { useTranslation } from "react-i18next";

import { Button } from "./ui";

/** Registruje service worker a nabídne obnovení, když je venku nová verze aplikace. */
export default function UpdatePrompt() {
  const { t } = useTranslation();
  const {
    needRefresh: [needRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisterError: (err) => console.warn("Service worker se nepodařilo zaregistrovat", err),
  });
  if (!needRefresh) return null;
  return (
    <div
      role="status"
      className="fixed inset-x-3 bottom-20 z-[70] mx-auto flex max-w-md items-center gap-3 rounded-xl bg-slate-900 px-4 py-3 text-sm text-white shadow-lg sm:bottom-6 dark:bg-slate-100 dark:text-slate-900"
    >
      <span className="flex-1">{t("offline.updateReady")}</span>
      <Button size="sm" variant="primary" onClick={() => void updateServiceWorker(true)}>
        {t("offline.reload")}
      </Button>
    </div>
  );
}
