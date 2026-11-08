import { Download, Smartphone, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { bannerHiddenRecently, hideBanner, useInstall } from "../lib/install";
import { Button, IconButton, Modal } from "./ui";

const HIDE_DAYS = 14;

/**
 * Tlačítko „Nainstalovat aplikaci“. Když prohlížeč umí instalaci nabídnout, spustí ji;
 * jinak otevře návod podle zařízení (iPhone, Android, počítač) a upozorní na chybějící HTTPS.
 * Nainstalovaná aplikace tlačítko neukazuje.
 */
export function InstallButton({
  size = "sm",
  className,
  onDone,
}: {
  size?: "sm" | "md";
  className?: string;
  onDone?: () => void;
}) {
  const { t } = useTranslation();
  const inst = useInstall();
  const [help, setHelp] = useState(false);
  if (inst.installed) return null;
  return (
    <>
      <Button
        size={size}
        className={className}
        onClick={async () => {
          if (inst.canPrompt) {
            const result = await inst.prompt();
            if (result !== "unavailable") onDone?.();
          } else setHelp(true);
        }}
      >
        <Download className="size-4" /> {t("install.button")}
      </Button>
      <InstallHelp open={help} onClose={() => setHelp(false)} />
    </>
  );
}

/** Nenápadný pruh nad obsahem (jen telefon): nabídne instalaci, jde skrýt na 14 dní. */
export function InstallBanner() {
  const { t } = useTranslation();
  const inst = useInstall();
  // Skrytí platí 14 dní; čas se čte jen při prvním vykreslení (ne při každém renderu).
  const [hidden, setHidden] = useState(() => bannerHiddenRecently(HIDE_DAYS));
  const [help, setHelp] = useState(false);
  // Pruh se ukáže tam, kde instalace opravdu jde: Android (nabídka od prohlížeče) a iPhone (ručně)
  const show = !inst.installed && !hidden && (inst.canPrompt || inst.ios);
  if (!show) return null;
  return (
    <div
      role="region"
      aria-label={t("install.bannerLabel")}
      className="flex items-center gap-2 border-b border-brand-200 bg-brand-50 px-3 py-2 text-sm md:hidden dark:border-brand-700/40 dark:bg-brand-700/20"
    >
      <Smartphone className="size-5 shrink-0 text-brand-600" aria-hidden />
      <span className="min-w-0 flex-1">{t("install.banner")}</span>
      <Button
        size="sm"
        variant="primary"
        onClick={async () => {
          if (inst.canPrompt) await inst.prompt();
          else setHelp(true);
        }}
      >
        {inst.canPrompt ? t("install.install") : t("install.how")}
      </Button>
      <IconButton
        label={t("install.hide")}
        onClick={() => {
          hideBanner();
          setHidden(true);
        }}
      >
        <X className="size-4" />
      </IconButton>
      <InstallHelp open={help} onClose={() => setHelp(false)} />
    </div>
  );
}

function InstallHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const inst = useInstall();
  return (
    <Modal open={open} onClose={onClose} title={t("install.helpTitle")}>
      <div className="space-y-4 text-sm">
        {!inst.secure && (
          <p role="alert" className="rounded-lg bg-amber-50 p-3 dark:bg-amber-950/40">
            {t("install.insecure")}
          </p>
        )}
        {inst.ios ? (
          <section>
            <h3 className="mb-1 font-semibold">{t("install.iosTitle")}</h3>
            <ol className="list-decimal space-y-1 pl-5">
              <li>{t("install.ios1")}</li>
              <li>{t("install.ios2")}</li>
              <li>{t("install.ios3")}</li>
            </ol>
          </section>
        ) : (
          <>
            <section>
              <h3 className="mb-1 font-semibold">{t("install.androidTitle")}</h3>
              <ol className="list-decimal space-y-1 pl-5">
                <li>{t("install.android1")}</li>
                <li>{t("install.android2")}</li>
                <li>{t("install.android3")}</li>
              </ol>
            </section>
            <section>
              <h3 className="mb-1 font-semibold">{t("install.desktopTitle")}</h3>
              <p>{t("install.desktop")}</p>
            </section>
          </>
        )}
        <p className="text-slate-500">{t("install.why")}</p>
        <div className="flex justify-end">
          <Button onClick={onClose}>{t("install.close")}</Button>
        </div>
      </div>
    </Modal>
  );
}
