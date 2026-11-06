import { FolderTree, Package, Tag } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { useSearch } from "../api/hooks";
import { Input, Spinner } from "./ui";

/** Rychlé hledání (Ctrl+K): věci, umístění, kategorie. */
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

  const results = useSearch(debounced);
  if (!open) return null;

  const go = (to: string) => {
    onOpenChange(false);
    setQ("");
    navigate(to);
  };
  const data = results.data;
  const empty = data && !data.items.length && !data.locations.length && !data.categories.length;

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
        <div className="border-b border-slate-200 p-3 dark:border-slate-800">
          <Input
            autoFocus
            placeholder={t("search.placeholder")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="max-h-[60dvh] overflow-y-auto p-2">
          {results.isFetching && !data && <Spinner />}
          {!q.trim() && (
            <p className="p-4 text-center text-sm text-slate-500">{t("search.hint")}</p>
          )}
          {empty && <p className="p-4 text-center text-sm text-slate-500">{t("search.none")}</p>}
          {data && data.items.length > 0 && (
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
            </Group>
          )}
          {data && data.locations.length > 0 && (
            <Group title={t("nav.locations")}>
              {data.locations.map((l) => (
                <Row
                  key={l.id}
                  icon={<FolderTree className="size-4" />}
                  onClick={() => go(`/locations/${l.id}`)}
                >
                  <span className="font-medium">{l.name}</span>
                  <span className="text-xs text-slate-500">{l.full_name}</span>
                </Row>
              ))}
            </Group>
          )}
          {data && data.categories.length > 0 && (
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
