import clsx from "clsx";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  FolderInput,
  GitMerge,
  GripVertical,
  Pencil,
  Plus,
  Undo2,
  X,
} from "lucide-react";
import { type DragEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useCategories } from "../../api/hooks";
import type { Detection, DetectionOverrides } from "../../api/types";
import { LocationSelect, TagInput } from "../../components/Pickers";
import { Badge, Button, Field, IconButton, Input, Select, Textarea } from "../../components/ui";
import { flattenTree } from "../../lib/format";
import {
  type Choice,
  categoryPathOf,
  confidencePercent,
  confidenceTone,
  parsePath,
  pathToText,
  pathsEqual,
} from "../../lib/photos";
import type { Effective } from "../../lib/reviewGroups";

const NEW_CATEGORY = "__new__";

export interface DragHandlers {
  onDragStart: (e: DragEvent<HTMLElement>) => void;
  onDragEnd: () => void;
}

/**
 * Jedna nalezená věc v kontrole: sbalený řádek (název, kategorie, umístění, množství, jistota
 * a rychlá rozhodnutí) a po rozbalení podrobnosti a úpravy. Řádek jde vybrat, přesunout
 * dialogem nebo přetáhnout do jiné skupiny.
 */
export default function DetectionRow({
  detection: d,
  index,
  choice,
  overrides,
  eff,
  flash,
  active,
  expanded,
  selected,
  drag,
  onSelect,
  onExpand,
  onToggleSelect,
  onChoice,
  onOverrides,
  onMove,
}: {
  detection: Detection;
  index: number;
  choice: Choice;
  overrides: DetectionOverrides;
  eff: Effective;
  /** krátké zvýraznění po úpravě asistentem */
  flash: boolean;
  active: boolean;
  expanded: boolean;
  selected: boolean;
  drag: DragHandlers | null;
  onSelect: () => void;
  onExpand: (open: boolean) => void;
  onToggleSelect: () => void;
  onChoice: (c: Choice) => void;
  onOverrides: (p: DetectionOverrides) => void;
  onMove: () => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const full = { ...d.suggested, ...overrides };
  const tone = confidenceTone(d.confidence);
  const m = d.matched_item;
  const toggle = (c: Choice) => onChoice(choice === c ? "pending" : c);
  const name = eff.name.trim() || d.label;
  const sug = d.suggested_location;
  const locText =
    eff.locationLabel ?? (eff.hasLocation ? t("photos.locationChosen") : t("items.unplaced"));
  const locId = overrides.location_path ? null : (eff.locationId ?? null);

  return (
    <article
      aria-label={t("photos.cardLabel", { n: index, name })}
      onClick={onSelect}
      className={clsx(
        "rounded-xl border bg-white text-sm dark:bg-slate-900",
        active
          ? "border-brand-500 ring-2 ring-brand-500/30"
          : "border-slate-200 dark:border-slate-800",
        flash && "ring-2 ring-amber-400",
        selected && "bg-brand-50/50 dark:bg-brand-700/10",
        choice === "accept" && "border-l-4 border-l-emerald-500",
        choice === "merge" && "border-l-4 border-l-sky-500",
        choice === "reject" && "opacity-60",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 p-2">
        {drag && (
          <span
            draggable
            onDragStart={drag.onDragStart}
            onDragEnd={drag.onDragEnd}
            onClick={(e) => e.stopPropagation()}
            title={t("photos.row.drag", { name })}
            aria-hidden
            className="hidden cursor-grab text-slate-400 active:cursor-grabbing md:block"
          >
            <GripVertical className="size-4" />
          </span>
        )}
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggleSelect}
          onClick={(e) => e.stopPropagation()}
          aria-label={t("photos.row.select", { name })}
          className="size-4 shrink-0"
        />
        <span className="flex size-5 shrink-0 items-center justify-center rounded bg-slate-900 text-[11px] font-bold text-white dark:bg-slate-100 dark:text-slate-900">
          {index}
        </span>
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={
            expanded ? t("photos.row.collapse", { name }) : t("photos.row.expand", { name })
          }
          onClick={(e) => {
            e.stopPropagation();
            onExpand(!expanded);
          }}
          className="flex min-w-0 flex-1 basis-48 items-center gap-1 text-left"
        >
          {expanded ? (
            <ChevronDown className="size-4 shrink-0 text-slate-400" aria-hidden />
          ) : (
            <ChevronRight className="size-4 shrink-0 text-slate-400" aria-hidden />
          )}
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5">
              <span className="truncate font-medium">{name}</span>
              {!eff.hasName && <Badge tone="amber">{t("photos.row.unnamed")}</Badge>}
              {m && <Badge tone="amber">{t("photos.row.duplicate")}</Badge>}
            </span>
            <span className="block truncate text-xs text-slate-500">
              <span className={eff.hasCategory ? "" : "text-amber-600"}>
                {eff.hasCategory ? eff.categoryPath.join(" › ") : t("items.noCategory")}
              </span>
              {" · "}
              <span className={eff.hasLocation ? "" : "text-amber-600"}>{locText}</span>
              {" · "}
              {eff.quantity} {eff.unit}
            </span>
          </span>
        </button>
        <Badge tone={tone === "green" ? "green" : tone === "amber" ? "amber" : "red"}>
          <span className="sr-only">{t("photos.confidence")}: </span>
          {confidencePercent(d.confidence)}
        </Badge>

        <div className="flex flex-wrap items-center gap-1" onClick={(e) => e.stopPropagation()}>
          {m ? (
            <>
              <Button
                size="sm"
                variant={choice === "accept" ? "primary" : "secondary"}
                aria-pressed={choice === "accept"}
                aria-label={t("photos.addAsNew")}
                title={t("photos.addAsNew")}
                onClick={() => toggle("accept")}
              >
                <Plus className="size-4" />
                <span className="hidden 2xl:inline">{t("photos.addAsNew")}</span>
              </Button>
              <Button
                size="sm"
                variant={choice === "merge" ? "primary" : "secondary"}
                aria-pressed={choice === "merge"}
                aria-label={t("photos.mergeExisting")}
                title={t("photos.mergeExisting")}
                onClick={() => toggle("merge")}
              >
                <GitMerge className="size-4" />
                <span className="hidden 2xl:inline">{t("photos.mergeExisting")}</span>
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant={choice === "accept" ? "primary" : "secondary"}
              aria-pressed={choice === "accept"}
              aria-label={t("photos.accept")}
              title={t("photos.accept")}
              onClick={() => toggle("accept")}
            >
              <Check className="size-4" />
              <span className="hidden 2xl:inline">{t("photos.accept")}</span>
            </Button>
          )}
          <Button
            size="sm"
            variant={choice === "reject" ? "danger" : "secondary"}
            aria-pressed={choice === "reject"}
            aria-label={t("photos.reject")}
            title={t("photos.reject")}
            onClick={() => toggle("reject")}
          >
            <X className="size-4" />
            <span className="hidden 2xl:inline">{t("photos.reject")}</span>
          </Button>
          {choice !== "reject" && (
            <Button
              size="sm"
              variant="ghost"
              aria-expanded={editing}
              aria-label={editing ? t("photos.hideEdit") : t("common.edit")}
              title={editing ? t("photos.hideEdit") : t("common.edit")}
              onClick={() => {
                const next = !editing;
                setEditing(next);
                if (next) onExpand(true);
              }}
            >
              <Pencil className="size-4" />
              <span className="hidden 2xl:inline">
                {editing ? t("photos.hideEdit") : t("common.edit")}
              </span>
            </Button>
          )}
          {choice !== "pending" && (
            <IconButton label={t("photos.resetChoice")} onClick={() => onChoice("pending")}>
              <Undo2 className="size-4" />
            </IconButton>
          )}
          <IconButton label={t("photos.move.one", { name })} onClick={onMove}>
            <FolderInput className="size-4" />
          </IconButton>
        </div>
      </div>

      {expanded && (
        <div className="space-y-2 border-t border-slate-100 p-3 dark:border-slate-800">
          {d.description && <p className="text-xs text-slate-500">{d.description}</p>}
          {full.text_read && (
            <p className="text-xs text-slate-500">
              {t("photos.textRead")}: <q>{full.text_read}</q>
            </p>
          )}
          <div className="text-xs text-slate-600 dark:text-slate-400">
            <span className="font-medium">{t("items.location")}:</span> {locText}
            {!overrides.location_id && !overrides.location_path && sug?.reason && (
              <span className="text-slate-500"> ({sug.reason})</span>
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
        </div>
      )}
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
export function CategoryPathField({
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
