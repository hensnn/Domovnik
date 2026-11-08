import clsx from "clsx";
import {
  AlertTriangle,
  Check,
  GitMerge,
  Maximize2,
  Pencil,
  Plus,
  Sparkles,
  Undo2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useCategories } from "../../api/hooks";
import type {
  Detection,
  DetectionDecision,
  DetectionOverrides,
  PhotoAnalysis,
  RefineEdit,
} from "../../api/types";
import { LocationSelect, TagInput } from "../../components/Pickers";
import { thumbUrl } from "../../components/Thumb";
import { Badge, Button, Field, Input, Select, Textarea, useToast } from "../../components/ui";
import { flattenTree } from "../../lib/format";
import {
  type Choice,
  type ReviewState,
  type UndoEntry,
  acceptConfident,
  applyRefineEdits,
  buildDecisions,
  buildDraft,
  categoryPathOf,
  confidencePercent,
  confidenceTone,
  initialChoice,
  mergeOverrides,
  parsePath,
  pathToText,
  pathsEqual,
  revertRefine,
  summarize,
} from "../../lib/photos";

import PhotoViewer from "./PhotoViewer";
import ReviewAssistant from "./ReviewAssistant";

const NEW_CATEGORY = "__new__";

export default function ReviewScreen({
  analysis,
  committing,
  error,
  onCommit,
  onCancel,
}: {
  analysis: PhotoAnalysis;
  committing: boolean;
  error: string | null;
  onCommit: (decisions: DetectionDecision[]) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const dets = analysis.detections;
  const [choices, setChoices] = useState<Record<string, Choice>>(() =>
    Object.fromEntries(dets.map((d) => [d.id, initialChoice(d)])),
  );
  const [overrides, setOverrides] = useState<Record<string, DetectionOverrides>>({});
  const [active, setActive] = useState<string | null>(null);
  const [viewer, setViewer] = useState(false);
  const [assistant, setAssistant] = useState(false);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [flash, setFlash] = useState<Set<string>>(new Set());
  const cardRefs = useRef<Record<string, HTMLElement | null>>({});
  // Poslední stav kontroly pro asistenta (odpověď přijde asynchronně, po dalších úpravách).
  const latest = useRef<ReviewState>({ choices, overrides, labels });
  useEffect(() => {
    latest.current = { choices, overrides, labels };
  });
  const flashTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(flashTimer.current), []);

  const sum = summarize(choices);
  const confidentLeft = dets.filter(
    (d) => choices[d.id] === "pending" && d.confidence >= 0.8 && !d.matched_item,
  ).length;

  const select = (id: string, scroll: boolean) => {
    setActive(id);
    if (scroll) cardRefs.current[id]?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  };

  const patchOverrides = (d: Detection, patch: DetectionOverrides) => {
    // ruční změna umístění zruší popisek, který nastavil asistent
    if ("location_id" in patch || "location_path" in patch) {
      setLabels((all) => Object.fromEntries(Object.entries(all).filter(([id]) => id !== d.id)));
    }
    setOverrides((all) => ({ ...all, [d.id]: mergeOverrides(d, all[d.id] ?? {}, patch) }));
  };

  const flashCards = (ids: string[]) => {
    window.clearTimeout(flashTimer.current);
    setFlash(new Set(ids));
    flashTimer.current = window.setTimeout(() => setFlash(new Set()), 2500);
  };
  const setState = (st: ReviewState) => {
    latest.current = st;
    setChoices(st.choices);
    setOverrides(st.overrides);
    setLabels(st.labels);
  };
  const applyEdits = (edits: RefineEdit[]) => {
    const r = applyRefineEdits(dets, latest.current, edits);
    setState(r.next);
    flashCards(r.touched);
    if (r.touched[0]) select(r.touched[0], true);
    const indexes = r.touched.map((id) => dets.findIndex((d) => d.id === id) + 1);
    return { undo: r.undo, touched: r.touched, indexes };
  };
  const undoEdits = (undo: UndoEntry[]) => {
    setState(revertRefine(latest.current, undo));
    flashCards(undo.map((u) => u.detection_id));
  };

  const acceptAll = () => {
    const r = acceptConfident(dets, choices);
    setChoices(r.choices);
    toast(t("photos.acceptedAll", { count: r.accepted }));
  };

  return (
    <div>
      <div className="md:grid md:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] md:gap-4">
        <div className="sticky top-0 z-10 -mx-3 bg-slate-50 px-3 pb-2 pt-1 md:top-3 md:mx-0 md:self-start md:bg-transparent md:p-0 dark:bg-slate-950 md:dark:bg-transparent">
          <PhotoWithBoxes
            fileId={analysis.file_id}
            detections={dets}
            choices={choices}
            active={active}
            onSelect={(id) => select(id, true)}
            onEnlarge={() => setViewer(true)}
          />
          {analysis.scene && (
            <p className="mt-1 text-xs text-slate-500">
              {t("photos.scene")}: {analysis.scene}
            </p>
          )}
        </div>

        <div className="mt-2 space-y-3 md:mt-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="mr-auto font-semibold">{t("photos.found", { count: dets.length })}</h2>
            <Button
              size="sm"
              aria-pressed={assistant}
              onClick={() => setAssistant((v) => !v)}
              disabled={dets.length === 0}
            >
              <Sparkles className="size-4" /> {t("photos.assistant.button")}
            </Button>
            <Button size="sm" onClick={acceptAll} disabled={confidentLeft === 0}>
              <Check className="size-4" /> {t("photos.acceptConfident")}
            </Button>
          </div>

          {dets.length === 0 && (
            <p className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
              {t("photos.nothingFound")}
            </p>
          )}

          <ul className="space-y-3">
            {dets.map((d, i) => (
              <li
                key={d.id}
                ref={(el) => {
                  cardRefs.current[d.id] = el;
                }}
              >
                <DetectionCard
                  detection={d}
                  index={i + 1}
                  choice={choices[d.id] ?? "pending"}
                  overrides={overrides[d.id] ?? {}}
                  locLabel={labels[d.id]}
                  flash={flash.has(d.id)}
                  active={active === d.id}
                  onSelect={() => select(d.id, false)}
                  onChoice={(c) => setChoices((all) => ({ ...all, [d.id]: c }))}
                  onOverrides={(p) => patchOverrides(d, p)}
                />
              </li>
            ))}
          </ul>
        </div>
      </div>

      {viewer && (
        <PhotoViewer
          src={`/api/v1/files/${analysis.file_id}`}
          detections={dets}
          choices={choices}
          active={active}
          onSelect={(id) => select(id, true)}
          onChoice={(id, c) => setChoices((all) => ({ ...all, [id]: c }))}
          onClose={() => setViewer(false)}
        />
      )}

      <div className="sticky bottom-0 -mx-3 mt-4 border-t border-slate-200 bg-white/95 px-3 py-3 backdrop-blur md:-mx-5 md:px-5 dark:border-slate-800 dark:bg-slate-900/95">
        {assistant && (
          <ReviewAssistant
            analysisId={analysis.id}
            getDraft={() => buildDraft(dets, latest.current)}
            apply={applyEdits}
            undo={undoEdits}
            onClose={() => setAssistant(false)}
          />
        )}
        {error && (
          <p role="alert" className="mb-2 text-sm text-red-600">
            {error}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <p className="mr-auto text-sm text-slate-600 dark:text-slate-300" aria-live="polite">
            {t("photos.summary", {
              accepted: sum.created,
              merged: sum.merged,
              rejected: sum.rejected,
              pending: sum.pending,
            })}
          </p>
          <Button onClick={onCancel} disabled={committing}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={sum.save === 0 || committing}
            onClick={() => onCommit(buildDecisions(dets, choices, overrides))}
          >
            {committing ? t("photos.saving") : t("photos.save", { count: sum.save })}
          </Button>
        </div>
      </div>
    </div>
  );
}

// --- Fotka s rámečky ------------------------------------------------------------------------

function PhotoWithBoxes({
  fileId,
  detections,
  choices,
  active,
  onSelect,
  onEnlarge,
}: {
  fileId: string;
  detections: Detection[];
  choices: Record<string, Choice>;
  active: string | null;
  onSelect: (id: string) => void;
  onEnlarge: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="relative mx-auto w-fit max-w-full overflow-hidden rounded-xl bg-slate-200 dark:bg-slate-800">
      <img
        src={thumbUrl(fileId, 1024)}
        alt={t("photos.photoAlt")}
        onClick={onEnlarge}
        className="block max-h-[30dvh] w-auto max-w-full cursor-zoom-in md:max-h-[72dvh]"
      />
      <button
        type="button"
        onClick={onEnlarge}
        aria-label={t("photos.viewer.enlarge")}
        title={t("photos.viewer.enlarge")}
        className="absolute right-1.5 top-1.5 z-20 flex items-center gap-1 rounded-lg bg-slate-900/75 px-2 py-1.5 text-xs font-medium text-white hover:bg-slate-900"
      >
        <Maximize2 className="size-4" /> {t("photos.viewer.enlargeShort")}
      </button>
      {detections.map((d, i) => {
        if (!d.bbox) return null;
        const [x, y, w, h] = d.bbox;
        const choice = choices[d.id] ?? "pending";
        const tone =
          choice === "accept"
            ? "border-emerald-500"
            : choice === "merge"
              ? "border-sky-500"
              : choice === "reject"
                ? "border-slate-400 border-dashed opacity-60"
                : confidenceTone(d.confidence) === "green"
                  ? "border-emerald-400"
                  : confidenceTone(d.confidence) === "amber"
                    ? "border-amber-400"
                    : "border-red-500";
        return (
          <button
            key={d.id}
            type="button"
            aria-label={t("photos.boxLabel", { n: i + 1, name: d.suggested.name || d.label })}
            aria-pressed={active === d.id}
            onClick={() => onSelect(d.id)}
            style={{
              left: `${x * 100}%`,
              top: `${y * 100}%`,
              width: `${w * 100}%`,
              height: `${h * 100}%`,
            }}
            className={clsx(
              "absolute rounded-sm border-2 bg-white/5 focus-visible:outline-2 focus-visible:outline-white",
              tone,
              active === d.id && "z-10 !border-4 bg-white/20 shadow-[0_0_0_2px_rgba(0,0,0,0.5)]",
            )}
          >
            <span className="absolute -left-0.5 -top-0.5 rounded-br bg-slate-900/80 px-1 text-[10px] font-bold leading-4 text-white">
              {i + 1}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// --- Karta detekce --------------------------------------------------------------------------

function DetectionCard({
  detection: d,
  index,
  choice,
  overrides,
  locLabel,
  flash,
  active,
  onSelect,
  onChoice,
  onOverrides,
}: {
  detection: Detection;
  index: number;
  choice: Choice;
  overrides: DetectionOverrides;
  /** čitelný název umístění vybraného asistentem */
  locLabel?: string;
  /** krátké zvýraznění po úpravě asistentem */
  flash: boolean;
  active: boolean;
  onSelect: () => void;
  onChoice: (c: Choice) => void;
  onOverrides: (p: DetectionOverrides) => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const eff = { ...d.suggested, ...overrides };
  const tone = confidenceTone(d.confidence);
  const locId = overrides.location_path
    ? null
    : (overrides.location_id ?? d.suggested_location?.id ?? null);
  const newPathText = overrides.location_path?.length
    ? `${overrides.location_path.join(" › ")} (${t("photos.assistant.newLocation")})`
    : undefined;
  const chosenText = locLabel ?? newPathText;
  const locPath =
    d.suggested_location?.path?.join(" › ") ?? d.suggested_location?.full_name ?? undefined;
  const m = d.matched_item;
  const toggle = (c: Choice) => onChoice(choice === c ? "pending" : c);

  return (
    <article
      aria-label={t("photos.cardLabel", { n: index, name: eff.name })}
      onClick={onSelect}
      className={clsx(
        "space-y-2 rounded-xl border bg-white p-3 text-sm dark:bg-slate-900",
        active
          ? "border-brand-500 ring-2 ring-brand-500/30"
          : "border-slate-200 dark:border-slate-800",
        flash && "ring-2 ring-amber-400",
        choice === "accept" && "border-l-4 border-l-emerald-500",
        choice === "merge" && "border-l-4 border-l-sky-500",
        choice === "reject" && "opacity-60",
      )}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded bg-slate-900 text-[11px] font-bold text-white dark:bg-slate-100 dark:text-slate-900">
          {index}
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-medium">{eff.name || d.label}</div>
          <div className="text-xs text-slate-500">
            {eff.category_path.length ? eff.category_path.join(" › ") : t("items.noCategory")} ·{" "}
            {eff.quantity} {eff.unit}
          </div>
        </div>
        <Badge tone={tone === "green" ? "green" : tone === "amber" ? "amber" : "red"}>
          <span className="sr-only">{t("photos.confidence")}: </span>
          {confidencePercent(d.confidence)}
        </Badge>
      </div>

      {d.description && <p className="text-xs text-slate-500">{d.description}</p>}
      {eff.text_read && (
        <p className="text-xs text-slate-500">
          {t("photos.textRead")}: <q>{eff.text_read}</q>
        </p>
      )}

      <div className="text-xs text-slate-600 dark:text-slate-400">
        <span className="font-medium">{t("items.location")}:</span>{" "}
        {chosenText ? (
          chosenText
        ) : overrides.location_id ? (
          t("photos.locationChosen")
        ) : locPath ? (
          <>
            {locPath}
            {d.suggested_location?.reason && (
              <span className="text-slate-500"> ({d.suggested_location.reason})</span>
            )}
          </>
        ) : locId ? (
          t("photos.locationChosen")
        ) : (
          t("items.unplaced")
        )}
      </div>

      {m && (
        <div
          role="note"
          className="flex items-start gap-2 rounded-lg bg-amber-50 p-2 text-xs dark:bg-amber-950/40"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" aria-hidden />
          <span>
            {t("photos.duplicate", { name: m.name })}{" "}
            <span className="text-slate-500">
              {m.label_code}
              {m.location_path ? ` · ${m.location_path}` : ""}
            </span>
          </span>
        </div>
      )}

      {editing && (
        <EditFields detection={d} overrides={overrides} locId={locId} onChange={onOverrides} />
      )}

      <div className="flex flex-wrap gap-2 pt-1" onClick={(e) => e.stopPropagation()}>
        {m ? (
          <>
            <Button
              size="sm"
              variant={choice === "accept" ? "primary" : "secondary"}
              aria-pressed={choice === "accept"}
              onClick={() => toggle("accept")}
            >
              <Plus className="size-4" /> {t("photos.addAsNew")}
            </Button>
            <Button
              size="sm"
              variant={choice === "merge" ? "primary" : "secondary"}
              aria-pressed={choice === "merge"}
              onClick={() => toggle("merge")}
            >
              <GitMerge className="size-4" /> {t("photos.mergeExisting")}
            </Button>
          </>
        ) : (
          <Button
            size="sm"
            variant={choice === "accept" ? "primary" : "secondary"}
            aria-pressed={choice === "accept"}
            onClick={() => toggle("accept")}
          >
            <Check className="size-4" /> {t("photos.accept")}
          </Button>
        )}
        <Button
          size="sm"
          variant={choice === "reject" ? "danger" : "secondary"}
          aria-pressed={choice === "reject"}
          onClick={() => toggle("reject")}
        >
          <X className="size-4" /> {t("photos.reject")}
        </Button>
        {choice !== "reject" && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setEditing((v) => !v)}
            aria-expanded={editing}
          >
            <Pencil className="size-4" /> {editing ? t("photos.hideEdit") : t("common.edit")}
          </Button>
        )}
        {choice !== "pending" && (
          <Button size="sm" variant="ghost" onClick={() => onChoice("pending")}>
            <Undo2 className="size-4" /> {t("photos.resetChoice")}
          </Button>
        )}
      </div>
    </article>
  );
}

function EditFields({
  detection: d,
  overrides,
  locId,
  onChange,
}: {
  detection: Detection;
  overrides: DetectionOverrides;
  locId: string | null;
  onChange: (p: DetectionOverrides) => void;
}) {
  const { t } = useTranslation();
  const eff = { ...d.suggested, ...overrides };
  const [qty, setQty] = useState(String(eff.quantity));

  return (
    <div
      className="space-y-3 border-t border-slate-200 pt-3 dark:border-slate-800"
      onClick={(e) => e.stopPropagation()}
    >
      <Field label={t("items.name")}>
        {(id) => (
          <Input id={id} value={eff.name} onChange={(e) => onChange({ name: e.target.value })} />
        )}
      </Field>
      <Field label={t("items.category")}>
        {(id) => (
          <CategoryPathField
            id={id}
            value={eff.category_path}
            onChange={(p) => onChange({ category_path: p })}
          />
        )}
      </Field>
      <Field label={t("items.tags")}>
        {(id) => <TagInput id={id} value={eff.tags} onChange={(v) => onChange({ tags: v })} />}
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("items.quantity")}>
          {(id) => (
            <Input
              id={id}
              inputMode="decimal"
              value={qty}
              onChange={(e) => {
                setQty(e.target.value);
                const n = Number(e.target.value.replace(",", "."));
                if (Number.isFinite(n) && n > 0) onChange({ quantity: n });
              }}
            />
          )}
        </Field>
        <Field label={t("items.unit")}>
          {(id) => (
            <Input id={id} value={eff.unit} onChange={(e) => onChange({ unit: e.target.value })} />
          )}
        </Field>
      </div>
      <Field label={t("items.location")}>
        {(id) => (
          <LocationSelect
            id={id}
            value={locId}
            onChange={(v) => onChange({ location_id: v ?? undefined })}
            emptyLabel={t("items.unplaced")}
          />
        )}
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("items.brand")}>
          {(id) => (
            <Input
              id={id}
              value={eff.brand ?? ""}
              onChange={(e) => onChange({ brand: e.target.value })}
            />
          )}
        </Field>
        <Field label={t("items.model")}>
          {(id) => (
            <Input
              id={id}
              value={eff.model ?? ""}
              onChange={(e) => onChange({ model: e.target.value })}
            />
          )}
        </Field>
      </div>
      <Field label={t("items.notes")}>
        {(id) => (
          <Textarea
            id={id}
            rows={2}
            value={eff.notes ?? ""}
            onChange={(e) => onChange({ notes: e.target.value })}
          />
        )}
      </Field>
    </div>
  );
}

/** Kategorie: výběr ze stromu, nebo nová cesta zapsaná jako „Nářadí > Ruční“. */
function CategoryPathField({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string[];
  onChange: (path: string[]) => void;
}) {
  const { t } = useTranslation();
  const { data: cats = [] } = useCategories();
  const flat = useMemo(() => flattenTree(cats), [cats]);
  const paths = useMemo(
    () => flat.map(({ node }) => ({ node, path: categoryPathOf(node, cats) })),
    [flat, cats],
  );
  const existing = paths.find((p) => pathsEqual(p.path, value));
  const [newMode, setNewMode] = useState(false);
  const [text, setText] = useState(pathToText(value));
  const isNew = newMode || (!existing && value.length > 0);

  return (
    <div className="space-y-2">
      <Select
        id={id}
        value={isNew ? NEW_CATEGORY : (existing?.node.id ?? "")}
        onChange={(e) => {
          const v = e.target.value;
          if (v === NEW_CATEGORY) {
            setNewMode(true);
            setText(pathToText(value));
          } else {
            setNewMode(false);
            onChange(v ? (paths.find((p) => p.node.id === v)?.path ?? []) : []);
          }
        }}
      >
        <option value="">{t("items.noCategory")}</option>
        {paths.map(({ node, path }) => (
          <option key={node.id} value={node.id}>
            {"  ".repeat(path.length - 1)}
            {node.name}
          </option>
        ))}
        <option value={NEW_CATEGORY}>{t("photos.newCategory")}</option>
      </Select>
      {isNew && (
        <Input
          aria-label={t("photos.newCategoryPath")}
          placeholder={t("photos.newCategoryPlaceholder")}
          value={text}
          onChange={(e) => {
            setNewMode(true);
            setText(e.target.value);
            onChange(parsePath(e.target.value));
          }}
        />
      )}
    </div>
  );
}
