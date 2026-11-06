import clsx from "clsx";
import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useSettings } from "../../api/hooks";
import { Button, Checkbox, Field, Input, Modal, Select } from "../../components/ui";
import {
  MAX_LABELS_PER_PRINT,
  PAGE_FORMATS,
  type PageFormat,
  labelsPdfUrl,
  pageCount,
} from "./api";

/** Dialog „Vytisknout štítky“: formát archu, první volná buňka, otevření PDF v nové záložce. */
export default function PrintLabelsDialog({
  open,
  onClose,
  kind,
  ids,
  title,
  extraIds,
  extraLabel,
}: {
  open: boolean;
  onClose: () => void;
  kind: "item" | "location";
  ids: string[];
  title?: string;
  /** volitelná další ID (např. podřízená umístění), která lze zaškrtnutím přidat */
  extraIds?: string[];
  extraLabel?: string;
}) {
  if (!open) return null;
  return (
    <Dialog
      onClose={onClose}
      kind={kind}
      ids={ids}
      title={title}
      extraIds={extraIds}
      extraLabel={extraLabel}
    />
  );
}

function Dialog({
  onClose,
  kind,
  ids,
  title,
  extraIds = [],
  extraLabel,
}: {
  onClose: () => void;
  kind: "item" | "location";
  ids: string[];
  title?: string;
  extraIds?: string[];
  extraLabel?: string;
}) {
  const { t } = useTranslation();
  const settings = useSettings();
  const defFormat = settings.data?.find((s) => s.key === "labels.page_format")?.value;
  const defPath = settings.data?.find((s) => s.key === "labels.show_path")?.value;
  const [format, setFormat] = useState<PageFormat | null>(null);
  const [showPath, setShowPath] = useState<boolean | null>(null);
  const [start, setStart] = useState(0);
  const [withExtra, setWithExtra] = useState(false);

  const effFormat: PageFormat =
    format ??
    (typeof defFormat === "string" && defFormat in PAGE_FORMATS
      ? (defFormat as PageFormat)
      : "A4_3x8");
  const effShowPath = showPath ?? (typeof defPath === "boolean" ? defPath : true);
  const { cols, rows } = PAGE_FORMATS[effFormat];
  const perPage = cols * rows;
  const allIds = withExtra ? [...ids, ...extraIds.filter((i) => !ids.includes(i))] : ids;
  const count = Math.min(allIds.length, MAX_LABELS_PER_PRINT);
  const safeStart = Math.min(Math.max(0, start), perPage - 1);
  const url = labelsPdfUrl({
    kind,
    ids: allIds,
    format: effFormat,
    start: safeStart,
    showPath: effShowPath,
  });

  return (
    <Modal
      open
      onClose={onClose}
      title={title ?? t("labels.title")}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            onClick={() => setTimeout(onClose, 300)}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-brand-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            <ExternalLink className="size-4" /> {t("labels.openPdf")}
          </a>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-slate-600 dark:text-slate-300">
          {t("labels.summary", {
            count,
            pages: pageCount(count, effFormat, safeStart),
          })}
        </p>
        {allIds.length > MAX_LABELS_PER_PRINT && (
          <p role="alert" className="text-sm text-amber-700 dark:text-amber-300">
            {t("labels.tooMany", { max: MAX_LABELS_PER_PRINT })}
          </p>
        )}
        {extraIds.length > 0 && (
          <Checkbox
            label={extraLabel ?? t("labels.includeExtra", { count: extraIds.length })}
            checked={withExtra}
            onChange={setWithExtra}
          />
        )}
        <Field label={t("labels.format")}>
          {(id) => (
            <Select
              id={id}
              value={effFormat}
              onChange={(e) => {
                setFormat(e.target.value as PageFormat);
                setStart(0);
              }}
            >
              {(Object.keys(PAGE_FORMATS) as PageFormat[]).map((f) => (
                <option key={f} value={f}>
                  {t("labels.formatOption", {
                    cols: PAGE_FORMATS[f].cols,
                    rows: PAGE_FORMATS[f].rows,
                    size: PAGE_FORMATS[f].size,
                  })}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t("labels.start")} hint={t("labels.startHint")}>
          {(id) => (
            <Input
              id={id}
              type="number"
              min={1}
              max={perPage}
              inputMode="numeric"
              value={safeStart + 1}
              onChange={(e) => setStart(Math.max(0, (Number(e.target.value) || 1) - 1))}
            />
          )}
        </Field>
        <div
          role="group"
          aria-label={t("labels.sheetPreview")}
          className="mx-auto grid max-w-[16rem] gap-0.5 rounded border border-slate-300 bg-slate-100 p-1 dark:border-slate-700 dark:bg-slate-800"
          style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
        >
          {Array.from({ length: perPage }, (_, i) => {
            const used = i < safeStart;
            const filled = i >= safeStart && i < safeStart + count;
            return (
              <button
                key={i}
                type="button"
                aria-label={t("labels.cell", { n: i + 1 })}
                aria-pressed={i === safeStart}
                onClick={() => setStart(i)}
                className={clsx(
                  "h-4 rounded-sm border text-[0px]",
                  used && "border-slate-300 bg-slate-300 dark:border-slate-600 dark:bg-slate-600",
                  filled && "border-brand-600 bg-brand-500",
                  !used &&
                    !filled &&
                    "border-slate-300 bg-white dark:border-slate-600 dark:bg-slate-900",
                  i === safeStart && "ring-2 ring-brand-600 ring-offset-1",
                )}
              >
                {i + 1}
              </button>
            );
          })}
        </div>
        <Checkbox label={t("labels.showPath")} checked={effShowPath} onChange={setShowPath} />
      </div>
    </Modal>
  );
}
