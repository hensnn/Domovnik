import { FolderTree, Package, Tag } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { useSearch } from "../api/hooks";
import type { LocationKind, SearchScope } from "../api/types";
import { LOCATION_KINDS } from "../lib/format";
import { Chip, Input, Spinner } from "./ui";

const SCOPES: SearchScope[] = ["all", "items", "locations", "categories"];

/** Rychlé hledání (Ctrl+K): věci, umístění (i podle druhu, např. „nábytek“), kategorie. */
export default function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [scope, setScope] = useState<SearchScope>("all");
  const [kinds, setKinds] = useState<LocationKind[]>([]);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(q), 200);
    return () => clearTimeout(id);
  }, [q]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenChange(true);
      } else if (e.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onOpenChange]);

  // Zúžený výběr (jeden typ / druh umístění) ukáže víc nálezů než souhrn.
  const results = useSearch(debounced, { scope, kinds, limit: scope === "all" ? 8 : 50 });
  if (!open) return null;

  const go = (to: string) => {
    onOpenChange(false);
    setQ("");
    setScope("all");
    setKinds([]);
    navigate(to);
  };
  const toggleKind = (k: LocationKind) => {
    setKinds((cur) => (cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k]));
    setScope("locations"); // druh se týká jen umístění
  };
  const data = results.data;
  const hasQuery = q.trim().length > 0 || kinds.length > 0;
  const empty = data && !data.items.length && !data.locations.length && !data.categories.length;
  const more = (key: "items" | "locations" | "categories", shown: number) => {
    const total = data?.totals?.[key] ?? 0;
    return scope === "all" && total > shown ? (
      <button
        onClick={() => setScope(key)}
        className="w-full rounded-lg px-2 py-1.5 text-left text-xs text-brand-700 hover:bg-slate-100 dark:text-brand-100 dark:hover:bg-slate-800"
      >
        {t("search.showAll", { count: total })}
      </button>
    ) : null;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-3 pt-[10dvh]">
      <div
        className="absolute inset-0 bg-slate-900/50"
        onClick={() => onOpenChange(false)}
        aria-hidden
      />
      <div
        role="dialog"
        aria-label={t("search.open")}
        className="relative w-full max-w-xl overflow-hidden rounded-2xl bg-white shadow-xl dark:bg-slate-900"
      >
        <div className="space-y-2 border-b border-slate-200 p-3 dark:border-slate-800">
          <Input
            autoFocus
            placeholder={t("search.placeholder")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <div className="flex flex-wrap gap-1" role="group" aria-label={t("search.scopeLabel")}>
            {SCOPES.map((s) => (
              <Chip key={s} active={scope === s} onClick={() => setScope(s)}>
                {t(`search.scope.${s}`)}
              </Chip>
            ))}
          </div>
          <div
            className="flex flex-wrap items-center gap-1"
            role="group"
            aria-label={t("search.kindLabel")}
          >
            <span className="mr-1 text-xs text-slate-500">{t("search.kindLabel")}:</span>
            {LOCATION_KINDS.map((k) => (
              <Chip key={k} active={kinds.includes(k)} onClick={() => toggleKind(k)}>
                {t(`kind.${k}`)}
              </Chip>
            ))}
          </div>
        </div>
        <div className="max-h-[55dvh] overflow-y-auto p-2">
          {results.isFetching && !data && <Spinner />}
          {!hasQuery && (
            <p className="p-4 text-center text-sm text-slate-500">{t("search.hint")}</p>
          )}
          {hasQuery && empty && (
            <p className="p-4 text-center text-sm text-slate-500">{t("search.none")}</p>
          )}
          {hasQuery && data && data.items.length > 0 && (
            <Group title={t("nav.items")}>
              {data.items.map((i) => (
                <Row
                  key={i.id}
                  icon={<Package className="size-4" />}
                  onClick={() => go(`/items/${i.id}`)}
                >
                  <span className="font-medium">{i.name}</span>
                  <span className="text-xs text-slate-500">
                    {i.placements[0]?.location_path ?? t("items.unplaced")} · {i.label_code}
                  </span>
                </Row>
              ))}
              {more("items", data.items.length)}
              {q.trim() && (
                <button
                  onClick={() => go(`/items?q=${encodeURIComponent(q.trim())}`)}
                  className="w-full rounded-lg px-2 py-1.5 text-left text-xs text-brand-700 hover:bg-slate-100 dark:text-brand-100 dark:hover:bg-slate-800"
                >
                  {t("search.openInItems")}
                </button>
              )}
            </Group>
          )}
          {hasQuery && data && data.locations.length > 0 && (
            <Group title={t("nav.locations")}>
              {data.locations.map((l) => (
                <Row
                  key={l.id}
                  icon={<FolderTree className="size-4" />}
                  onClick={() => go(`/locations/${l.id}`)}
                >
                  <span className="font-medium">{l.name}</span>
                  <span className="text-xs text-slate-500">
                    {t(`kind.${l.kind}`)} · {l.full_name}
                  </span>
                </Row>
              ))}
              {more("locations", data.locations.length)}
            </Group>
          )}
          {hasQuery && data && data.categories.length > 0 && (
            <Group title={t("nav.categories")}>
              {data.categories.map((c) => (
                <Row
                  key={c.id}
                  icon={<Tag className="size-4" />}
                  onClick={() => go(`/items?category_id=${c.id}`)}
                >
                  <span className="font-medium">{c.name}</span>
                  <span className="text-xs text-slate-500">{c.item_count}×</span>
                </Row>
              ))}
              {more("categories", data.categories.length)}
            </Group>
          )}
        </div>
      </div>
    </div>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-2">
      <div className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {title}
      </div>
      {children}
    </div>
  );
}

function Row({
  icon,
  onClick,
  children,
}: {
  icon: React.ReactNode;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800"
    >
      <span className="text-slate-400">{icon}</span>
      <span className="flex min-w-0 flex-1 flex-col">{children}</span>
    </button>
  );
}
