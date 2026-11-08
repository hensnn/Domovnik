import clsx from "clsx";
import {
  ChevronDown,
  ChevronRight,
  Check,
  FolderInput,
  Maximize2,
  Sparkles,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useLocations } from "../../api/hooks";
import type {
  Detection,
  DetectionDecision,
  DetectionOverrides,
  PhotoAnalysis,
  RefineEdit,
} from "../../api/types";
import { thumbUrl } from "../../components/Thumb";
import { Button, Chip, useToast } from "../../components/ui";
import {
  type Choice,
  type ReviewState,
  type UndoEntry,
  acceptConfident,
  applyRefineEdits,
  buildDecisions,
  buildDraft,
  confidenceTone,
  initialChoice,
  mergeOverrides,
  revertRefine,
  summarize,
} from "../../lib/photos";
import {
  type Group,
  type GroupMode,
  type Move,
  dropOnGroup,
  effectiveOf,
  groupDetections,
  moveDetections,
} from "../../lib/reviewGroups";
import DetectionRow from "./DetectionRow";
import MoveDialog from "./MoveDialog";
import PhotoViewer from "./PhotoViewer";
import ReviewAssistant from "./ReviewAssistant";

const MODES: GroupMode[] = ["triage", "location", "category", "decision"];
/** Do tohoto počtu nálezů jsou řádky rozbalené, u delších seznamů sbalené pro přehlednost. */
const EXPAND_ALL_UP_TO = 6;

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
  const [mode, setMode] = useState<GroupMode>("triage");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(dets.length <= EXPAND_ALL_UP_TO ? dets.map((d) => d.id) : []),
  );
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [moving, setMoving] = useState<string[] | null>(null);
  const [dragIds, setDragIds] = useState<string[] | null>(null);
  const [overGroup, setOverGroup] = useState<string | null>(null);
  const cardRefs = useRef<Record<string, HTMLElement | null>>({});
  // Poslední stav kontroly pro asistenta (odpověď přijde asynchronně, po dalších úpravách).
  const latest = useRef<ReviewState>({ choices, overrides, labels });
  useEffect(() => {
    latest.current = { choices, overrides, labels };
  });
  const flashTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(flashTimer.current), []);

  const { data: locations = [] } = useLocations();
  const locName = useCallback(
    (id: string) => locations.find((l) => l.id === id)?.full_name ?? undefined,
    [locations],
  );

  const eff = useMemo(
    () =>
      new Map(
        dets.map((d) => [d.id, effectiveOf(d, overrides[d.id] ?? {}, labels, locName)] as const),
      ),
    [dets, overrides, labels, locName],
  );
  const groups = useMemo(
    () => groupDetections(dets, { choices, overrides, labels, locName }, mode),
    [dets, choices, overrides, labels, locName, mode],
  );
  const indexOf = useMemo(() => new Map(dets.map((d, i) => [d.id, i + 1] as const)), [dets]);

  const sum = summarize(choices);
  const confidentLeft = dets.filter(
    (d) => choices[d.id] === "pending" && d.confidence >= 0.8 && !d.matched_item,
  ).length;

  const select = (id: string, scroll: boolean) => {
    setActive(id);
    if (!scroll) return;
    // z fotky: rozbalí řádek i jeho skupinu a doskroluje k němu
    setExpanded((s) => new Set(s).add(id));
    const g = groups.find((x) => x.ids.includes(id));
    if (g) setCollapsedGroups((s) => new Set([...s].filter((k) => k !== g.key)));
    window.setTimeout(
      () => cardRefs.current[id]?.scrollIntoView?.({ block: "nearest", behavior: "smooth" }),
      0,
    );
  };

  const patchOverrides = (d: Detection, patch: DetectionOverrides) => {
    // ruční změna umístění zruší popisek, který nastavil asistent nebo přesun
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
    const indexes = r.touched.map((id) => indexOf.get(id) ?? 0);
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

  // --- výběr, sbalení, přesun --------------------------------------------------------------
  const toggleSet = (setter: typeof setSelected, id: string) =>
    setter((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const toggleGroupSelection = (g: Group) =>
    setSelected((s) => {
      const all = g.ids.every((id) => s.has(id));
      const n = new Set(s);
      g.ids.forEach((id) => (all ? n.delete(id) : n.add(id)));
      return n;
    });
  const allGroupsCollapsed = groups.length > 0 && groups.every((g) => collapsedGroups.has(g.key));
  const toggleAllGroups = () => {
    if (allGroupsCollapsed) {
      setCollapsedGroups(new Set());
      setExpanded(new Set(dets.map((d) => d.id)));
    } else {
      setCollapsedGroups(new Set(groups.map((g) => g.key)));
    }
  };

  const applyMove = (ids: string[], move: Move) => {
    const r = moveDetections(dets, latest.current, ids, move);
    setState(r.next);
    flashCards(ids);
    toast(t("photos.move.done", { count: r.count }));
  };
  const setChoiceFor = (ids: string[], c: Choice) =>
    setChoices((all) => {
      const next = { ...all };
      const dup = new Set(dets.filter((d) => d.matched_item).map((d) => d.id));
      ids.forEach((id) => {
        if (c !== "merge" || dup.has(id)) next[id] = c;
      });
      return next;
    });

  const startDrag = (id: string) => {
    const ids = selected.has(id) ? [...selected] : [id];
    setDragIds(ids);
    return ids;
  };
  const dropOn = (g: Group) => {
    const ids = dragIds;
    setDragIds(null);
    setOverGroup(null);
    if (!ids || !g.drop) return;
    const r = dropOnGroup(dets, latest.current, ids, g.drop);
    setState(r.next);
    flashCards(ids);
    toast(t("photos.move.done", { count: r.count }));
  };

  const groupTitle = (g: Group): string => {
    switch (g.kind) {
      case "unnamed":
      case "nocat":
      case "noloc":
      case "done":
        return t(`photos.group.${g.kind}`);
      case "decision":
        return t(`photos.group.${g.choice ?? "pending"}`);
      default:
        return g.title ?? "";
    }
  };
  const groupHint = (g: Group): string | null =>
    ["unnamed", "nocat", "noloc", "done"].includes(g.kind) ? t(`photos.group.${g.kind}Hint`) : null;

  return (
    <div>
      <div className="lg:grid lg:grid-cols-[minmax(300px,36%)_minmax(0,1fr)] lg:gap-4 2xl:grid-cols-[minmax(380px,34%)_minmax(0,1fr)]">
        <div className="sticky top-0 z-10 -mx-3 bg-slate-50 px-3 pb-2 pt-1 lg:top-3 lg:mx-0 lg:self-start lg:bg-transparent lg:p-0 dark:bg-slate-950 lg:dark:bg-transparent">
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

        <div className="mt-2 min-w-0 space-y-3 lg:mt-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="mr-auto font-semibold">{t("photos.found", { count: dets.length })}</h2>
            <Button size="sm" onClick={toggleAllGroups} disabled={dets.length === 0}>
              {allGroupsCollapsed ? (
                <ChevronDown className="size-4" />
              ) : (
                <ChevronRight className="size-4" />
              )}
              {allGroupsCollapsed ? t("photos.toolbar.expandAll") : t("photos.toolbar.collapseAll")}
            </Button>
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

          {dets.length > 0 && (
            <div
              className="flex flex-wrap items-center gap-1"
              role="group"
              aria-label={t("photos.mode.label")}
            >
              <span className="mr-1 text-xs text-slate-500">{t("photos.mode.label")}:</span>
              {MODES.map((m) => (
                <Chip key={m} active={mode === m} onClick={() => setMode(m)}>
                  {t(`photos.mode.${m}`)}
                </Chip>
              ))}
            </div>
          )}

          {selected.size > 0 && (
            <div
              role="region"
              aria-label={t("photos.selection.label")}
              className="flex flex-wrap items-center gap-2 rounded-lg bg-brand-600 p-2 text-sm text-white shadow"
            >
              <span className="px-2 font-medium">
                {t("photos.selection.count", { count: selected.size })}
              </span>
              <Button size="sm" onClick={() => setMoving([...selected])}>
                <FolderInput className="size-4" /> {t("photos.selection.move")}
              </Button>
              <Button size="sm" onClick={() => setChoiceFor([...selected], "accept")}>
                {t("photos.accept")}
              </Button>
              <Button size="sm" onClick={() => setChoiceFor([...selected], "reject")}>
                {t("photos.reject")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="!text-white"
                onClick={() => setSelected(new Set())}
              >
                <X className="size-4" /> {t("photos.selection.clear")}
              </Button>
            </div>
          )}

          {dets.length === 0 && (
            <p className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-slate-700">
              {t("photos.nothingFound")}
            </p>
          )}

          {groups.map((g) => {
            const title = groupTitle(g);
            const hint = groupHint(g);
            const collapsed = collapsedGroups.has(g.key);
            const droppable = !!dragIds && !!g.drop;
            const allSelected = g.ids.every((id) => selected.has(id));
            return (
              <section
                key={g.key}
                aria-label={title}
                onDragOver={(e) => {
                  if (!droppable) return;
                  e.preventDefault();
                  e.dataTransfer.dropEffect = "move";
                  setOverGroup(g.key);
                }}
                onDragLeave={() => setOverGroup((k) => (k === g.key ? null : k))}
                onDrop={(e) => {
                  if (!droppable) return;
                  e.preventDefault();
                  dropOn(g);
                }}
                className={clsx(
                  "rounded-xl border p-2",
                  g.kind === "unnamed" || g.kind === "nocat" || g.kind === "noloc"
                    ? "border-amber-300 bg-amber-50/40 dark:border-amber-700/50 dark:bg-amber-950/10"
                    : "border-slate-200 dark:border-slate-800",
                  droppable && g.drop && "border-dashed",
                  overGroup === g.key &&
                    "!border-brand-500 bg-brand-50 ring-2 ring-brand-500/40 dark:bg-brand-700/20",
                )}
              >
                <div className="flex items-center gap-2 px-1 pb-1">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={() => toggleGroupSelection(g)}
                    aria-label={t("photos.group.selectAll", { title })}
                    className="size-4"
                  />
                  <button
                    type="button"
                    aria-expanded={!collapsed}
                    aria-label={
                      collapsed
                        ? t("photos.group.expand", { title })
                        : t("photos.group.collapse", { title })
                    }
                    onClick={() => toggleSet(setCollapsedGroups, g.key)}
                    className="flex min-w-0 flex-1 items-center gap-1 text-left"
                  >
                    {collapsed ? (
                      <ChevronRight className="size-4 shrink-0 text-slate-400" aria-hidden />
                    ) : (
                      <ChevronDown className="size-4 shrink-0 text-slate-400" aria-hidden />
                    )}
                    <span className="truncate font-semibold">{title}</span>
                    <span className="rounded-full bg-slate-200 px-2 text-xs dark:bg-slate-700">
                      {g.ids.length}
                    </span>
                    {hint && (
                      <span className="hidden truncate text-xs text-slate-500 sm:inline">
                        {hint}
                      </span>
                    )}
                  </button>
                  {droppable && g.drop && (
                    <span className="text-xs text-brand-700 dark:text-brand-100">
                      {t("photos.group.dropHere")}
                    </span>
                  )}
                </div>
                {!collapsed && (
                  <ul className="space-y-2">
                    {g.ids.map((id) => {
                      const d = dets.find((x) => x.id === id)!;
                      return (
                        <li
                          key={id}
                          ref={(el) => {
                            cardRefs.current[id] = el;
                          }}
                        >
                          <DetectionRow
                            detection={d}
                            index={indexOf.get(id) ?? 0}
                            choice={choices[id] ?? "pending"}
                            overrides={overrides[id] ?? {}}
                            eff={eff.get(id)!}
                            flash={flash.has(id)}
                            active={active === id}
                            expanded={expanded.has(id)}
                            selected={selected.has(id)}
                            drag={{
                              onDragStart: (e) => {
                                const ids = startDrag(id);
                                e.dataTransfer.effectAllowed = "move";
                                e.dataTransfer.setData("text/plain", ids.join(","));
                                const row = cardRefs.current[id];
                                if (row) e.dataTransfer.setDragImage(row, 20, 20);
                              },
                              onDragEnd: () => {
                                setDragIds(null);
                                setOverGroup(null);
                              },
                            }}
                            onSelect={() => select(id, false)}
                            onExpand={(open) =>
                              setExpanded((s) => {
                                const n = new Set(s);
                                if (open) n.add(id);
                                else n.delete(id);
                                return n;
                              })
                            }
                            onToggleSelect={() => toggleSet(setSelected, id)}
                            onChoice={(c) => setChoices((all) => ({ ...all, [id]: c }))}
                            onOverrides={(p) => patchOverrides(d, p)}
                            onMove={() => setMoving([id])}
                          />
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            );
          })}
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

      {moving && (
        <MoveDialog
          count={moving.length}
          onApply={(move) => {
            applyMove(moving, move);
            setMoving(null);
          }}
          onClose={() => setMoving(null)}
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
