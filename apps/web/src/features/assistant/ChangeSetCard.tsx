import type { TFunction } from "i18next";
import clsx from "clsx";
import { AlertTriangle, Check, CircleX, Undo2, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api_, useApiMutation } from "../../api/hooks";
import { ApiError } from "../../api/client";
import type { ChangeSet, ChangeSetStatus } from "../../api/types";
import { Badge, Button, errorMessage, useToast } from "../../components/ui";

const TONE: Record<ChangeSetStatus, "slate" | "green" | "amber" | "red" | "blue"> = {
  proposed: "blue",
  applied: "green",
  partially_applied: "amber",
  rejected: "slate",
  undone: "slate",
  failed: "red",
};

/** Srozumitelná hláška k chybě při potvrzování / vracení změn (409 = stav se mezitím změnil). */
export function changeSetError(err: unknown, t: TFunction): string {
  if (err instanceof ApiError && err.status === 409) {
    return `${t("changes.conflict")} ${err.message}`;
  }
  return errorMessage(err);
}

/** Karta balíčku změn: diff operací, potvrzení / zamítnutí / vrácení zpět. */
export default function ChangeSetCard({
  changeSet,
  canWrite = true,
  onChange,
}: {
  changeSet: ChangeSet;
  canWrite?: boolean;
  onChange?: (cs: ChangeSet) => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const [cs, setCs] = useState(changeSet);
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const done = (next: ChangeSet, message?: string) => {
    setCs(next);
    setError(null);
    onChange?.(next);
    if (message) toast(message);
  };
  const fail = (e: unknown) => setError(changeSetError(e, t));

  const apply = useApiMutation((ids: string[]) => api_.applyChangeSet(cs.id, ids), {
    onSuccess: (res) => done(res, t("changes.appliedToast")),
  });
  const reject = useApiMutation(() => api_.rejectChangeSet(cs.id), {
    onSuccess: (res) => done(res, t("changes.rejectedToast")),
  });
  const undo = useApiMutation(() => api_.undoChangeSet(cs.id), {
    onSuccess: (res) => done(res, t("changes.undoneToast")),
  });
  const busy = apply.isPending || reject.isPending || undo.isPending;

  const proposed = cs.status === "proposed";
  // u částečně provedeného balíčku API `reversible` nevyplňuje (null) – vrátit lze i tak
  const canUndo =
    canWrite &&
    (cs.status === "applied" || cs.status === "partially_applied") &&
    cs.reversible !== false;
  const selectedCount = cs.operations.filter((o) => !skipped.has(o.id)).length;
  const toggle = (id: string, on: boolean) => {
    const next = new Set(skipped);
    if (on) next.delete(id);
    else next.add(id);
    setSkipped(next);
  };

  return (
    <section
      aria-label={t("changes.title")}
      className="space-y-3 rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900"
    >
      <header className="flex flex-wrap items-center gap-2">
        <Badge tone={TONE[cs.status]}>{t(`changes.status.${cs.status}`)}</Badge>
        {cs.risky && (
          <Badge tone="amber">
            <AlertTriangle className="mr-1 size-3" aria-hidden /> {t("changes.risky")}
          </Badge>
        )}
        <h4 className="min-w-0 flex-1 text-sm font-semibold">{cs.summary}</h4>
      </header>

      <ul className="space-y-1.5 text-sm">
        {cs.operations.map((op) => {
          const skippedNow = proposed && skipped.has(op.id);
          const failedOp = op.status === "failed" || !!op.error;
          return (
            <li key={op.id} className="flex items-start gap-2">
              {proposed && canWrite ? (
                <input
                  type="checkbox"
                  id={`op-${op.id}`}
                  checked={!skippedNow}
                  onChange={(e) => toggle(op.id, e.target.checked)}
                  className="mt-0.5 size-4 shrink-0 accent-brand-600"
                />
              ) : (
                <OpIcon status={op.status} />
              )}
              <label
                htmlFor={proposed && canWrite ? `op-${op.id}` : undefined}
                className={clsx(
                  "min-w-0 flex-1 break-words",
                  skippedNow && "text-slate-400 line-through",
                  op.status === "skipped" && "text-slate-400 line-through",
                  failedOp && "text-red-700 dark:text-red-400",
                )}
              >
                {op.description}
                {op.error && <span className="block text-xs">{op.error}</span>}
              </label>
            </li>
          );
        })}
      </ul>

      {proposed && cs.needs_ui_confirmation && (
        <p className="text-xs text-amber-700 dark:text-amber-400">{t("changes.needsUi")}</p>
      )}

      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}

      {canWrite && proposed && (
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            size="sm"
            disabled={busy || selectedCount === 0}
            onClick={() => apply.mutate([...skipped], { onError: fail })}
          >
            <Check className="size-4" />
            {skipped.size ? t("changes.applySome", { count: selectedCount }) : t("changes.apply")}
          </Button>
          <Button
            size="sm"
            disabled={busy}
            onClick={() => reject.mutate(undefined, { onError: fail })}
          >
            <X className="size-4" /> {t("changes.reject")}
          </Button>
        </div>
      )}

      {canUndo && (
        <div>
          <Button
            size="sm"
            disabled={busy}
            onClick={() => undo.mutate(undefined, { onError: fail })}
          >
            <Undo2 className="size-4" /> {t("changes.undo")}
          </Button>
        </div>
      )}
    </section>
  );
}

function OpIcon({ status }: { status: string }) {
  if (status === "applied")
    return <Check className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden />;
  if (status === "failed")
    return <CircleX className="mt-0.5 size-4 shrink-0 text-red-600" aria-hidden />;
  if (status === "undone")
    return <Undo2 className="mt-0.5 size-4 shrink-0 text-slate-500" aria-hidden />;
  return <span className="mt-1.5 size-2 shrink-0 rounded-full bg-slate-300" aria-hidden />;
}
