import { X } from "lucide-react";
import { type KeyboardEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { useCategories, useLocations, useTags } from "../api/hooks";
import { flattenTree } from "../lib/format";
import { Select } from "./ui";

const indent = (depth: number) => "  ".repeat(depth) + (depth ? "└ " : "");

export function LocationSelect({
  value,
  onChange,
  id,
  allowEmpty = true,
  emptyLabel,
  exclude,
}: {
  value: string | null | undefined;
  onChange: (v: string | null) => void;
  id?: string;
  allowEmpty?: boolean;
  emptyLabel?: string;
  /** id umístění (včetně potomků), které se nenabízí (např. při přesunu do sebe) */
  exclude?: string;
}) {
  const { t } = useTranslation();
  const { data = [] } = useLocations();
  const flat = flattenTree(data);
  const excluded = new Set<string>();
  if (exclude) {
    excluded.add(exclude);
    for (const { node } of flat)
      if (node.parent_id && excluded.has(node.parent_id)) excluded.add(node.id);
  }
  return (
    <Select id={id} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      {allowEmpty && <option value="">{emptyLabel ?? t("common.none")}</option>}
      {flat
        .filter(({ node }) => !excluded.has(node.id))
        .map(({ node, depth }) => (
          <option key={node.id} value={node.id}>
            {indent(depth)}
            {node.name}
          </option>
        ))}
    </Select>
  );
}

export function CategorySelect({
  value,
  onChange,
  id,
  allowEmpty = true,
  emptyLabel,
  exclude,
}: {
  value: string | null | undefined;
  onChange: (v: string | null) => void;
  id?: string;
  allowEmpty?: boolean;
  emptyLabel?: string;
  exclude?: string;
}) {
  const { t } = useTranslation();
  const { data = [] } = useCategories();
  const flat = flattenTree(data);
  const excluded = new Set<string>();
  if (exclude) {
    excluded.add(exclude);
    for (const { node } of flat)
      if (node.parent_id && excluded.has(node.parent_id)) excluded.add(node.id);
  }
  return (
    <Select id={id} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      {allowEmpty && <option value="">{emptyLabel ?? t("common.none")}</option>}
      {flat
        .filter(({ node }) => !excluded.has(node.id))
        .map(({ node, depth }) => (
          <option key={node.id} value={node.id}>
            {indent(depth)}
            {node.name}
          </option>
        ))}
    </Select>
  );
}

/** Zadávání štítků (tagů): Enter / čárka přidá, nabízí existující. */
export function TagInput({
  value,
  onChange,
  id,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  id?: string;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const { data: all = [] } = useTags();
  const listId = `${id ?? "tags"}-list`;

  const add = (raw: string) => {
    const name = raw.trim();
    if (!name || value.some((v) => v.toLowerCase() === name.toLowerCase())) return;
    onChange([...value, name]);
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add(text);
      setText("");
    } else if (e.key === "Backspace" && !text && value.length) {
      onChange(value.slice(0, -1));
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2 py-1.5 focus-within:ring-2 focus-within:ring-brand-500/30 dark:border-slate-700 dark:bg-slate-900">
      {value.map((tag) => (
        <span
          key={tag}
          className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800"
        >
          {tag}
          <button
            type="button"
            aria-label={t("common.remove", { name: tag })}
            onClick={() => onChange(value.filter((v) => v !== tag))}
          >
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input
        id={id}
        list={listId}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        onBlur={() => {
          add(text);
          setText("");
        }}
        placeholder={value.length ? "" : t("items.tagsPlaceholder")}
        className="min-w-24 flex-1 bg-transparent py-0.5 text-sm outline-none"
      />
      <datalist id={listId}>
        {all.map((tg) => (
          <option key={tg.id} value={tg.name} />
        ))}
      </datalist>
    </div>
  );
}
