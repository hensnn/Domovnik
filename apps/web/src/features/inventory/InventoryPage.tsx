import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, ClipboardCheck, Minus, Plus, ScanLine, X } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import { useItems } from "../../api/hooks";
import { LocationSelect } from "../../components/Pickers";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  Modal,
  Spinner,
  errorMessage,
  useToast,
} from "../../components/ui";
import { formatDateTime, formatQty } from "../../lib/format";
import { setCurrentLocation, useCurrentLocation } from "../../lib/currentLocation";
import { normalizeCode } from "../../lib/labelCode";
import { useAuth } from "../auth/AuthProvider";
import { type ResolveResult, resolveCode } from "../labels/api";
import QrScanner from "../scan/QrScanner";
import {
  type InventoryDetail,
  type InventoryLine,
  type LineResult,
  inventoryApi,
  useCountLine,
  useInventorySession,
  useInventorySessions,
} from "./api";
import {
  type LineFilter,
  lineForScannedItem,
  matchesFilter,
  plannedChanges,
  progress,
  stepQty,
} from "./logic";

const RESULT_TONE: Record<LineResult, "slate" | "green" | "amber" | "red" | "blue"> = {
  unchecked: "slate",
  ok: "green",
  missing: "red",
  extra: "amber",
  moved: "blue",
};

export default function InventoryPage() {
  const { id } = useParams();
  return id ? <SessionView id={id} /> : <InventoryHome />;
}

// --- Přehled a založení ---------------------------------------------------------------------

function InventoryHome() {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { can } = useAuth();
  const [params] = useSearchParams();
  const [location, setLocation] = useState<string | null>(params.get("location"));
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sessions = useInventorySessions();

  const start = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const created = await inventoryApi.start({
        location_id: location,
        name: name.trim() || undefined,
      });
      void qc.invalidateQueries({ queryKey: ["inventory"] });
      toast(t("inventory.started", { count: created.counts.total }));
      navigate(`/inventory/${created.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-3 md:p-5">
      <h1 className="flex items-center gap-2 text-xl font-bold">
        <ClipboardCheck className="size-6 text-brand-600" /> {t("inventory.title")}
      </h1>
      <p className="text-sm text-slate-600 dark:text-slate-300">{t("inventory.intro")}</p>

      {can("items:write") && (
        <Card>
          <form onSubmit={start} className="space-y-3">
            <h2 className="font-semibold">{t("inventory.new")}</h2>
            <Field label={t("inventory.scope")} hint={t("inventory.scopeHint")}>
              {(id) => (
                <LocationSelect
                  id={id}
                  value={location}
                  onChange={setLocation}
                  emptyLabel={t("inventory.wholeHome")}
                />
              )}
            </Field>
            <Field label={t("inventory.nameLabel")}>
              {(id) => (
                <Input
                  id={id}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t("inventory.namePlaceholder")}
                />
              )}
            </Field>
            {error && (
              <p role="alert" className="text-sm text-red-600">
                {error}
              </p>
            )}
            <Button type="submit" variant="primary" disabled={busy}>
              <ClipboardCheck className="size-4" /> {t("inventory.start")}
            </Button>
          </form>
        </Card>
      )}

      <Card className="!p-0">
        <h2 className="border-b border-slate-200 px-4 py-3 font-semibold dark:border-slate-800">
          {t("inventory.history")}
        </h2>
        {sessions.isPending ? (
          <Spinner />
        ) : !sessions.data?.length ? (
          <EmptyState title={t("inventory.none")} hint={t("inventory.noneHint")} />
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {sessions.data.map((s) => (
              <li key={s.id}>
                <Link
                  to={`/inventory/${s.id}`}
                  className="flex items-center gap-3 px-4 py-3 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{s.name}</span>
                    <span className="block truncate text-xs text-slate-500">
                      {s.location_name ?? t("inventory.wholeHome")} · {formatDateTime(s.started_at)}
                    </span>
                  </span>
                  {s.status === "open" ? (
                    <Badge tone="blue">
                      {t("inventory.progress", {
                        done: s.counts.total - s.counts.unchecked,
                        total: s.counts.total,
                      })}
                    </Badge>
                  ) : (
                    <Badge tone={s.status === "closed" ? "green" : "slate"}>
                      {t(`inventory.status.${s.status}`)}
                    </Badge>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// --- Probíhající / uzavřená inventura --------------------------------------------------------

function SessionView({ id }: { id: string }) {
  const { t } = useTranslation();
  const toast = useToast();
  const { can } = useAuth();
  const { data, isPending, isError, error } = useInventorySession(id);
  const count = useCountLine(id);
  const [current] = useCurrentLocation();
  const [filter, setFilter] = useState<LineFilter>("all");
  const [scanning, setScanning] = useState(false);
  const [adding, setAdding] = useState<null | { item?: ResolveResult }>(null);
  const [closing, setClosing] = useState(false);
  const busy = useRef(false);
  const dataRef = useRef<InventoryDetail | undefined>(undefined);
  const currentRef = useRef(current);
  useEffect(() => {
    // čtečka kódu běží mimo vykreslování – potřebuje vždy čerstvá data
    dataRef.current = data;
    currentRef.current = current;
  });

  const setCount = useCallback(
    async (line: InventoryLine, counted: number | null) => {
      try {
        await count.mutateAsync({
          itemId: line.item_id,
          locationId: line.location_id,
          counted,
        });
      } catch (e) {
        toast(errorMessage(e), "error");
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [count.mutateAsync, toast],
  );

  const onScan = useCallback(
    async (raw: string) => {
      if (busy.current) return;
      busy.current = true;
      try {
        const found = await resolveCode(normalizeCode(raw));
        const session = dataRef.current;
        if (!session) return;
        if (found.type === "location") {
          setCurrentLocation(found.id);
          toast(t("scan.hereSet", { name: found.name }));
          return;
        }
        const line = lineForScannedItem(session.lines, found.id, currentRef.current);
        if (!line) {
          setAdding({ item: found });
        } else if (line.expected_qty === null || line.result !== "unchecked") {
          toast(t("inventory.alreadyChecked", { name: found.name }));
        } else {
          await setCount(line, Number(line.expected_qty));
          toast(t("inventory.scanTicked", { name: found.name }));
        }
      } catch (e) {
        toast(
          e instanceof ApiError && e.status === 404
            ? t("scan.notFound", { code: raw })
            : errorMessage(e),
          "error",
        );
      } finally {
        busy.current = false;
      }
    },
    [setCount, t, toast],
  );

  const groups = useMemo(() => {
    const map = new Map<string, { path: string; lines: InventoryLine[] }>();
    for (const l of data?.lines ?? []) {
      if (!matchesFilter(l, filter)) continue;
      const g = map.get(l.location_id) ?? {
        path: l.location_path ?? l.location_name ?? "",
        lines: [],
      };
      g.lines.push(l);
      map.set(l.location_id, g);
    }
    return [...map.entries()];
  }, [data?.lines, filter]);

  if (isPending) return <Spinner />;
  if (isError || !data) return <p className="p-4 text-red-600">{errorMessage(error)}</p>;

  const open = data.status === "open";
  const canWrite = can("items:write") && open;
  const pct = Math.round(progress(data.counts) * 100);

  return (
    <div className="mx-auto max-w-3xl space-y-3 p-3 md:p-5">
      <Link to="/inventory" className="text-sm text-brand-700 dark:text-brand-100">
        ← {t("inventory.title")}
      </Link>
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-bold">{data.name}</h1>
          <Badge tone={open ? "blue" : data.status === "closed" ? "green" : "slate"}>
            {t(`inventory.status.${data.status}`)}
          </Badge>
        </div>
        <p className="text-sm text-slate-500">
          {data.location_name ?? t("inventory.wholeHome")} · {formatDateTime(data.started_at)}
          {data.applied_at &&
            ` · ${t("inventory.appliedAt", { at: formatDateTime(data.applied_at) })}`}
        </p>
      </div>

      <div className="space-y-1">
        <div
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={t("inventory.progressLabel")}
          className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800"
        >
          <div className="h-full bg-brand-600 transition-all" style={{ width: `${pct}%` }} />
        </div>
        <div className="flex flex-wrap gap-1.5 text-xs">
          <Badge>
            {t("inventory.progress", {
              done: data.counts.total - data.counts.unchecked,
              total: data.counts.total,
            })}
          </Badge>
          {(["ok", "missing", "extra", "moved"] as const).map(
            (k) =>
              data.counts[k] > 0 && (
                <Badge key={k} tone={RESULT_TONE[k]}>
                  {t(`inventory.result.${k}`)}: {data.counts[k]}
                </Badge>
              ),
          )}
        </div>
      </div>

      {canWrite && (
        <div className="sticky top-0 z-10 -mx-3 flex flex-wrap gap-2 bg-slate-50/95 px-3 py-2 backdrop-blur md:mx-0 md:px-0 dark:bg-slate-950/95">
          <Button
            variant={scanning ? "primary" : "secondary"}
            onClick={() => setScanning((s) => !s)}
          >
            <ScanLine className="size-4" /> {t("inventory.scan")}
          </Button>
          <Button onClick={() => setAdding({})}>
            <Plus className="size-4" /> {t("inventory.addUnexpected")}
          </Button>
          <Button variant="primary" className="ml-auto" onClick={() => setClosing(true)}>
            {t("inventory.finish")}
          </Button>
        </div>
      )}

      {canWrite && scanning && (
        <Card>
          <QrScanner onCode={(raw) => void onScan(raw)} />
          <p className="mt-2 text-xs text-slate-500">{t("inventory.scanHint")}</p>
        </Card>
      )}

      <div role="tablist" aria-label={t("inventory.filter")} className="flex gap-1 text-sm">
        {(["all", "todo", "diff"] as const).map((f) => (
          <button
            key={f}
            role="tab"
            aria-selected={filter === f}
            onClick={() => setFilter(f)}
            className={clsx(
              "rounded-full px-3 py-1.5 font-medium",
              filter === f
                ? "bg-brand-600 text-white"
                : "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
            )}
          >
            {t(`inventory.filters.${f}`)}
          </button>
        ))}
      </div>

      {groups.length === 0 ? (
        <Card>
          <EmptyState
            title={
              data.counts.total === 0 ? t("inventory.emptySession") : t("inventory.emptyFilter")
            }
            hint={data.counts.total === 0 ? t("inventory.emptySessionHint") : undefined}
          />
        </Card>
      ) : (
        groups.map(([locationId, g]) => (
          <section key={locationId} aria-label={g.path} className="space-y-2">
            <h2
              className={clsx(
                "flex items-center gap-2 text-sm font-semibold text-slate-600 dark:text-slate-300",
                locationId === current && "text-brand-700 dark:text-brand-100",
              )}
            >
              {g.path}
              {locationId === current && <Badge tone="green">{t("scan.here")}</Badge>}
            </h2>
            <ul className="space-y-2">
              {g.lines.map((line) => (
                <LineRow
                  key={`${line.item_id}/${line.location_id}`}
                  line={line}
                  editable={canWrite}
                  onCount={(q) => void setCount(line, q)}
                />
              ))}
            </ul>
          </section>
        ))
      )}

      {adding && (
        <AddUnexpectedDialog
          session={data}
          preset={adding.item}
          onClose={() => setAdding(null)}
          onAdd={async (itemId, locationId, qty) => {
            await count.mutateAsync({ itemId, locationId, counted: qty });
            toast(t("inventory.added"));
          }}
        />
      )}
      {closing && <CloseDialog session={data} onClose={() => setClosing(false)} />}
    </div>
  );
}

// --- Řádek ----------------------------------------------------------------------------------

function LineRow({
  line,
  editable,
  onCount,
}: {
  line: InventoryLine;
  editable: boolean;
  onCount: (qty: number | null) => void;
}) {
  const { t } = useTranslation();
  const expected = line.expected_qty === null ? null : Number(line.expected_qty);
  const counted = line.counted_qty === null ? null : Number(line.counted_qty);
  const base = counted ?? expected ?? 1;
  const [draft, setDraft] = useState<string | null>(null);

  const commit = () => {
    if (draft === null) return;
    const n = Number(draft.replace(",", "."));
    setDraft(null);
    if (Number.isFinite(n) && n >= 0 && n !== counted) onCount(n);
  };

  const tone = {
    unchecked: "border-slate-200 dark:border-slate-800",
    ok: "border-emerald-400 bg-emerald-50/60 dark:border-emerald-800 dark:bg-emerald-950/30",
    missing: "border-red-400 bg-red-50/60 dark:border-red-800 dark:bg-red-950/30",
    extra: "border-amber-400 bg-amber-50/60 dark:border-amber-800 dark:bg-amber-950/30",
    moved: "border-sky-400 bg-sky-50/60 dark:border-sky-800 dark:bg-sky-950/30",
  }[line.result];

  const big =
    "min-h-12 min-w-12 rounded-xl text-base font-semibold disabled:opacity-40 inline-flex items-center justify-center";

  return (
    <li
      className={clsx("space-y-2 rounded-xl border bg-white p-3 dark:bg-slate-900", tone)}
      data-result={line.result}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <Link
            to={`/items/${line.item_id}`}
            className="block truncate font-medium hover:underline"
          >
            {line.item_name}
          </Link>
          <p className="text-xs text-slate-500">
            <span className="font-mono">{line.item_label_code}</span> ·{" "}
            {expected === null
              ? t("inventory.unexpected")
              : t("inventory.expected", { qty: formatQty(expected, line.unit) })}
          </p>
        </div>
        <Badge tone={RESULT_TONE[line.result]}>{t(`inventory.result.${line.result}`)}</Badge>
      </div>

      {editable && (
        <div className="flex items-center gap-2">
          <button
            type="button"
            className={clsx(big, "w-14 bg-red-600 text-white")}
            aria-label={t("inventory.markMissing", { name: line.item_name })}
            aria-pressed={line.result === "missing" && counted === 0}
            disabled={expected === null}
            onClick={() => onCount(0)}
          >
            <X className="size-6" />
          </button>
          <div className="flex flex-1 items-center justify-center gap-1">
            <button
              type="button"
              className={clsx(big, "w-12 border border-slate-300 dark:border-slate-700")}
              aria-label={t("inventory.less")}
              disabled={counted === 0 || (counted === null && base <= 0)}
              onClick={() => onCount(stepQty(base, -1))}
            >
              <Minus className="size-5" />
            </button>
            <div className="min-w-0 flex-1 text-center">
              <input
                aria-label={t("inventory.countedQty", { name: line.item_name })}
                inputMode="decimal"
                value={draft ?? (counted === null ? "" : String(counted))}
                placeholder="–"
                onChange={(e) => setDraft(e.target.value)}
                onBlur={commit}
                onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
                className="w-full rounded-lg border border-slate-300 bg-white py-2 text-center text-lg font-semibold dark:border-slate-700 dark:bg-slate-900"
              />
              <span className="text-xs text-slate-500">{line.unit}</span>
            </div>
            <button
              type="button"
              className={clsx(big, "w-12 border border-slate-300 dark:border-slate-700")}
              aria-label={t("inventory.more")}
              onClick={() => onCount(stepQty(base, 1))}
            >
              <Plus className="size-5" />
            </button>
          </div>
          <button
            type="button"
            className={clsx(big, "w-14 bg-emerald-600 text-white")}
            aria-label={t("inventory.markFound", { name: line.item_name })}
            aria-pressed={line.result === "ok"}
            onClick={() => onCount(expected ?? counted ?? 1)}
          >
            <Check className="size-6" />
          </button>
        </div>
      )}
      {!editable && counted !== null && (
        <p className="text-sm">
          {t("inventory.counted", { qty: formatQty(counted, line.unit) })}
          {line.diff !== null && Number(line.diff) !== 0 && (
            <span className="text-slate-500">
              {" "}
              ({Number(line.diff) > 0 ? "+" : ""}
              {formatQty(line.diff)})
            </span>
          )}
        </p>
      )}
      {editable && counted !== null && (
        <button
          type="button"
          className="text-xs text-slate-500 underline"
          onClick={() => onCount(null)}
        >
          {t(expected === null ? "inventory.removeLine" : "inventory.resetLine")}
        </button>
      )}
    </li>
  );
}

// --- Neočekávaná věc --------------------------------------------------------------------------

function AddUnexpectedDialog({
  session,
  preset,
  onClose,
  onAdd,
}: {
  session: InventoryDetail;
  preset?: ResolveResult;
  onClose: () => void;
  onAdd: (itemId: string, locationId: string, qty: number) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [current] = useCurrentLocation();
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<{ id: string; name: string } | null>(
    preset ? { id: preset.id, name: preset.name } : null,
  );
  const [location, setLocation] = useState<string | null>(current ?? session.location_id);
  const [qty, setQty] = useState("1");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const found = useItems({ q: q.trim(), limit: 8 });

  const valid = !!picked && !!location && Number(qty.replace(",", ".")) > 0;
  const submit = async () => {
    if (!picked || !location) return;
    setBusy(true);
    setError(null);
    try {
      await onAdd(picked.id, location, Number(qty.replace(",", ".")));
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={t("inventory.addUnexpected")}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={!valid || busy} onClick={() => void submit()}>
            {t("common.confirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-slate-500">{t("inventory.unexpectedHint")}</p>
        {picked ? (
          <div className="flex items-center gap-2 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
            <span className="min-w-0 flex-1 truncate font-medium">{picked.name}</span>
            <Button size="sm" onClick={() => setPicked(null)}>
              {t("inventory.changeItem")}
            </Button>
          </div>
        ) : (
          <div className="space-y-2">
            <Field label={t("inventory.findItem")}>
              {(id) => (
                <Input
                  id={id}
                  value={q}
                  autoFocus
                  onChange={(e) => setQ(e.target.value)}
                  placeholder={t("items.searchPlaceholder")}
                />
              )}
            </Field>
            {q.trim() && (
              <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
                {(found.data?.items ?? []).map((i) => (
                  <li key={i.id}>
                    <button
                      type="button"
                      className="flex w-full flex-col px-3 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
                      onClick={() => setPicked({ id: i.id, name: i.name })}
                    >
                      <span className="font-medium">{i.name}</span>
                      <span className="text-xs text-slate-500">
                        {i.placements[0]?.location_path ?? t("items.unplaced")}
                      </span>
                    </button>
                  </li>
                ))}
                {found.data && found.data.items.length === 0 && (
                  <li className="px-3 py-2 text-sm text-slate-500">{t("search.none")}</li>
                )}
              </ul>
            )}
          </div>
        )}
        <Field label={t("inventory.foundWhere")}>
          {(id) => <LocationSelect id={id} value={location} onChange={setLocation} allowEmpty />}
        </Field>
        <Field label={t("items.quantity")}>
          {(id) => (
            <Input
              id={id}
              inputMode="decimal"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
            />
          )}
        </Field>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}

// --- Uzavření ---------------------------------------------------------------------------------

function CloseDialog({ session, onClose }: { session: InventoryDetail; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const changes = plannedChanges(session.lines);
  const [apply, setApply] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (kind: "close" | "cancel") => {
    setBusy(true);
    setError(null);
    try {
      if (kind === "cancel") await inventoryApi.cancel(session.id);
      else await inventoryApi.close(session.id, apply && changes.length > 0);
      // změna množství se projeví ve věcech, umístěních i přehledu
      await qc.invalidateQueries();
      toast(t(kind === "cancel" ? "inventory.cancelled" : "inventory.closed"));
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={t("inventory.finishTitle")}
      wide
      footer={
        <>
          <Button variant="danger" disabled={busy} onClick={() => void run("cancel")}>
            {t("inventory.cancelSession")}
          </Button>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={busy} onClick={() => void run("close")}>
            {t("inventory.closeConfirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {session.counts.unchecked > 0 && (
          <p role="status" className="rounded-lg bg-amber-50 p-3 text-sm dark:bg-amber-950/40">
            {t("inventory.uncheckedWarning", { count: session.counts.unchecked })}
          </p>
        )}
        {changes.length === 0 ? (
          <p className="text-sm text-slate-600 dark:text-slate-300">{t("inventory.noChanges")}</p>
        ) : (
          <>
            <h3 className="font-semibold">
              {t("inventory.changesPreview", { count: changes.length })}
            </h3>
            <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-sm dark:divide-slate-800 dark:border-slate-800">
              {changes.map((c) => (
                <li
                  key={`${c.line.item_id}/${c.line.location_id}`}
                  className="flex items-center gap-2 px-3 py-2"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{c.line.item_name}</span>
                    <span className="block truncate text-xs text-slate-500">
                      {c.line.location_path}
                    </span>
                  </span>
                  <span className="whitespace-nowrap font-mono">
                    {formatQty(c.from)} → <strong>{formatQty(c.to, c.line.unit)}</strong>
                  </span>
                </li>
              ))}
            </ul>
            <div role="radiogroup" aria-label={t("inventory.applyChoice")} className="space-y-2">
              {[true, false].map((v) => (
                <label key={String(v)} className="flex cursor-pointer items-start gap-2 text-sm">
                  <input
                    type="radio"
                    name="apply"
                    checked={apply === v}
                    onChange={() => setApply(v)}
                    className="mt-1 accent-brand-600"
                  />
                  <span>
                    <span className="font-medium">
                      {t(v ? "inventory.applyYes" : "inventory.applyNo")}
                    </span>
                    <span className="block text-xs text-slate-500">
                      {t(v ? "inventory.applyYesHint" : "inventory.applyNoHint")}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </>
        )}
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
