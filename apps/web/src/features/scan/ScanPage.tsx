import { ClipboardCheck, FolderOpen, MapPin, PackagePlus, ScanLine } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../../api/client";
import { Button, Card, errorMessage, useToast } from "../../components/ui";
import { setCurrentLocation } from "../../lib/currentLocation";
import { normalizeCode, parseScannedText } from "../../lib/labelCode";
import { useAuth } from "../auth/AuthProvider";
import { type ResolveResult, resolveCode } from "../labels/api";
import QrScanner from "./QrScanner";

/** Stránka Skenovat: věc se otevře, umístění nastaví „Jsem tady“ a nabídne další akce. */
export default function ScanPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const { can } = useAuth();
  const [here, setHere] = useState<ResolveResult | null>(null);
  const busy = useRef(false);

  const handle = useCallback(
    async (raw: string) => {
      const text = parseScannedText(raw);
      if (!text || busy.current) return;
      busy.current = true;
      try {
        const found = await resolveCode(normalizeCode(text));
        if (found.type === "item") {
          navigate(`/items/${found.id}`);
        } else {
          setCurrentLocation(found.id);
          setHere(found);
          toast(t("scan.hereSet", { name: found.name }));
        }
      } catch (e) {
        toast(
          e instanceof ApiError && e.status === 404
            ? t("scan.notFound", { code: text })
            : errorMessage(e),
          "error",
        );
      } finally {
        busy.current = false;
      }
    },
    [navigate, t, toast],
  );

  return (
    <div className="mx-auto max-w-xl space-y-4 p-3 md:p-5">
      <h1 className="flex items-center gap-2 text-xl font-bold">
        <ScanLine className="size-6 text-brand-600" /> {t("scan.title")}
      </h1>

      {here ? (
        <Card className="space-y-3">
          <div className="flex items-start gap-3">
            <MapPin className="mt-0.5 size-6 shrink-0 text-brand-600" />
            <div className="min-w-0">
              <p className="text-sm text-slate-500">{t("scan.youAreHere")}</p>
              <p className="text-lg font-bold">{here.name}</p>
              {here.full_name && here.full_name !== here.name && (
                <p className="truncate text-sm text-slate-500">{here.full_name}</p>
              )}
              <p className="font-mono text-xs text-slate-400">{here.label_code}</p>
            </div>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {can("items:write") && (
              <Button
                variant="primary"
                onClick={() => navigate(`/items?location_id=${here.id}&new=1`)}
              >
                <PackagePlus className="size-4" /> {t("scan.addHere")}
              </Button>
            )}
            <Button onClick={() => navigate(`/locations/${here.id}`)}>
              <FolderOpen className="size-4" /> {t("scan.whatsHere")}
            </Button>
            {can("items:write") && (
              <Button onClick={() => navigate(`/inventory?location=${here.id}`)}>
                <ClipboardCheck className="size-4" /> {t("scan.inventoryHere")}
              </Button>
            )}
            <Button variant="ghost" onClick={() => setHere(null)}>
              <ScanLine className="size-4" /> {t("scan.again")}
            </Button>
          </div>
        </Card>
      ) : (
        <>
          <p className="text-sm text-slate-600 dark:text-slate-300">{t("scan.hint")}</p>
          <QrScanner onCode={(raw) => void handle(raw)} />
        </>
      )}
    </div>
  );
}
