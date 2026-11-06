import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import clsx from "clsx";
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  Columns3,
  Filter,
  LayoutGrid,
  Plus,
  Rows3,
  Search,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api_, useApiMutation, useItem, useItems, useSettings } from "../../api/hooks";
import type { Item, ItemFilters, ItemStatus } from "../../api/types";
import { CategorySelect, LocationSelect, TagInput } from "../../components/Pickers";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Drawer,
  EmptyState,
  Field,
  Input,
  Modal,
  Select,
  Spinner,
  errorMessage,
  useToast,
} from "../../components/ui";
import { STATUS_TONE, formatDate, formatQty, placementSummary } from "../../lib/format";
import { useStoredState } from "../../lib/storage";
import { useAuth } from "../auth/AuthProvider";
import ItemDetail from "./ItemDetail";
import ItemForm from "./ItemForm";

const STATUSES: ItemStatus[] = ["stored", "in_use", "lent", "repair", "discarded", "sold", "lost"];
const ALL_COLUMNS = [
  "label",
  "category",
  "location",
  "quantity",
  "status",
  "tags",
  "updated",
] as const;
type ColumnId = (typeof ALL_COLUMNS)[number];
const SORT_KEYS: Record<string, string> = {
  name: "name",
  label: "label",
  updated: "updated",
};

export default function ItemsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id: openId } = useParams();
  const [params, setParams] = useSearchParams();
  const { can } = useAuth();
  const canWrite = can("items:write");
  const settings = useSettings();
  const pageSize = Number(settings.data?.find((s) => s.key === "ui.page_size")?.value ?? 50);

  const filters: ItemFilters = {
    q: params.get("q") ?? undefined,
    category_id: params.get("category_id") ?? undefined,
    location_id: params.get("location_id") ?? undefined,
    status: (params.get("status") as ItemStatus | null) ?? undefined,
    tag: params.getAll("tag"),
    unplaced: params.get("unplaced") === "1" ? true : undefined,
    low_stock: params.get("low_stock") === "1" ? true : undefined,
    trash: params.get("trash") === "1" ? true : undefined,
    sort: params.get("sort") ?? (params.get("q") ? "relevance" : "name"),
    desc: params.get("desc") === "1",
    limit: pageSize,
    offset: Number(params.get("offset") ?? 0),
  };
  const activeFilterCount = [
    filters.category_id,
    filters.location_id,
    filters.status,
    filters.tag?.length ? "x" : "",
    filters.unplaced,
    filters.low_stock,
    filters.trash,
  ].filter(Boolean).length;

  const update = (patch: Record<string, string | string[] | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      next.delete(k);
      if (Array.isArray(v)) v.forEach((x) => next.append(k, x));
      else if (v !== null && v !== "") next.set(k, v);
    }
    if (!("offset" in patch)) next.delete("offset");
    setParams(next, { replace: true });
  };

  const { data, isPending, isError, error, isFetching } = useItems(filters);
  const [view, setView] = useStoredState<"table" | "cards">("items.view", "table");
  const [visible, setVisible] = useStoredState<ColumnId[]>("items.columns", [
    "category",
    "location",
    "quantity",
    "status",
    "updated",
  ]);
  const [showFilters, setShowFilters] = useState(false);
  const [showCols, setShowCols] = useState(false);
  const [creating, setCreating] = useState(params.get("new") === "1");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkOpen, setBulkOpen] = useState(false);

  // hledání s krátkým zpožděním
  const [qText, setQText] = useState(filters.q ?? "");
  useEffect(() => setQText(filters.q ?? ""), [filters.q]);
  useEffect(() => {
    const id = setTimeout(() => qText !== (filters.q ?? "") && update({ q: qText || null }), 300);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qText]);
  useEffect(() => setSelected(new Set()), [params.toString()]); // eslint-disable-line react-hooks/exhaustive-deps

  const sorting: SortingState = [{ id: filters.sort ?? "name", desc: !!filters.desc }];
  const columns = useMemo<ColumnDef<Item>[]>(
    () => [
      {
        id: "select",
        header: () => (
          <input
            type="checkbox"
            aria-label={t("common.selectAll")}
            checked={!!data?.items.length && data.items.every((i) => selected.has(i.id))}
            onChange={(e) =>
              setSelected(e.target.checked ? new Set(data?.items.map((i) => i.id)) : new Set())
            }
          />
        ),
        cell: ({ row }) => (
          <input
            type="checkbox"
            aria-label={t("common.select")}
            checked={selected.has(row.original.id)}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => {
              const next = new Set(selected);
              if (e.target.checked) next.add(row.original.id);
              else next.delete(row.original.id);
              setSelected(next);
            }}
          />
        ),
      },
      {
        id: "name",
        header: t("items.name"),
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="truncate font-medium">{row.original.name}</div>
            {row.original.brand && (
              <div className="truncate text-xs text-slate-500">{row.original.brand}</div>
            )}
          </div>
        ),
      },
      {
        id: "label",
        header: t("items.label"),
        cell: ({ row }) => <span className="font-mono text-xs">{row.original.label_code}</span>,
      },
      {
        id: "category",
        header: t("items.category"),
        enableSorting: false,
        cell: ({ row }) => row.original.category_path ?? "–",
      },
      {
        id: "location",
        header: t("items.location"),
        enableSorting: false,
        cell: ({ row }) =>
          row.original.placements.length ? (
            <span className="truncate">{placementSummary(row.original)}</span>
          ) : (
            <Badge tone="amber">{t("items.unplaced")}</Badge>
          ),
      },
      {
        id: "quantity",
        header: t("items.quantity"),
        enableSorting: false,
        cell: ({ row }) => (
          <span className={row.original.is_low_stock ? "font-semibold text-amber-600" : ""}>
            {formatQty(row.original.total_quantity, row.original.unit)}
          </span>
        ),
      },
      {
        id: "status",
        header: t("items.status"),
        enableSorting: false,
        cell: ({ row }) => (
          <Badge tone={STATUS_TONE[row.original.status]}>
            {t(`status.${row.original.status}`)}
          </Badge>
        ),
      },
      {
        id: "tags",
        header: t("items.tags"),
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.tags.slice(0, 3).map((x) => (
              <Badge key={x}>{x}</Badge>
            ))}
          </div>
        ),
      },
      {
        id: "updated",
        header: t("items.updated"),
        cell: ({ row }) => formatDate(row.original.updated_at),
      },
    ],
    [t, data, selected],
  );

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    state: {
      sorting,
      columnVisibility: Object.fromEntries(ALL_COLUMNS.map((c) => [c, visible.includes(c)])),
    },
    getRowId: (r) => r.id,
  });

  const total = data?.total ?? 0;
  const from = total ? filters.offset! + 1 : 0;
  const to = Math.min(total, filters.offset! + pageSize);
  const openItem = (id: string) => navigate(`/items/${id}?${params.toString()}`);
  const closeItem = () => navigate(`/items?${params.toString()}`);

  const toggleSort = (colId: string) => {
    const key = SORT_KEYS[colId];
    if (!key) return;
    if (filters.sort === key) update({ desc: filters.desc ? null : "1" });
    else update({ sort: key, desc: null });
  };

  return (
    <div className="mx-auto max-w-7xl space-y-3 p-3 md:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-xl font-bold">
          {filters.trash ? t("items.trash") : t("nav.items")}
          <span className="ml-2 text-sm font-normal text-slate-500">{total}</span>
        </h1>
        <div className="relative order-last w-full sm:order-none sm:w-auto sm:flex-none sm:basis-72">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          <Input
            value={qText}
            onChange={(e) => setQText(e.target.value)}
            placeholder={t("items.searchPlaceholder")}
            aria-label={t("items.searchPlaceholder")}
            className="pl-9"
          />
        </div>
        <Button onClick={() => setShowFilters((v) => !v)} aria-pressed={showFilters}>
          <Filter className="size-4" /> {t("items.filters")}
          {activeFilterCount > 0 && <Badge tone="blue">{activeFilterCount}</Badge>}
        </Button>
        <div className="hidden gap-1 md:flex">
          <Button
            aria-label={t("items.viewTable")}
            aria-pressed={view === "table"}
            onClick={() => setView("table")}
            className={view === "table" ? "!border-brand-500" : ""}
          >
            <Rows3 className="size-4" />
          </Button>
          <Button
            aria-label={t("items.viewCards")}
            aria-pressed={view === "cards"}
            onClick={() => setView("cards")}
            className={view === "cards" ? "!border-brand-500" : ""}
          >
            <LayoutGrid className="size-4" />
          </Button>
          <div className="relative">
            <Button aria-label={t("items.columns")} onClick={() => setShowCols((v) => !v)}>
              <Columns3 className="size-4" />
            </Button>
            {showCols && (
              <div className="absolute right-0 z-20 mt-1 w-48 space-y-2 rounded-lg border border-slate-200 bg-white p-3 shadow-lg dark:border-slate-700 dark:bg-slate-900">
                {ALL_COLUMNS.map((c) => (
                  <Checkbox
                    key={c}
                    label={t(`items.col.${c}`)}
                    checked={visible.includes(c)}
                    onChange={(on) =>
                      setVisible(on ? [...visible, c] : visible.filter((x) => x !== c))
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </div>
        {canWrite && !filters.trash && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus className="size-4" /> {t("items.add")}
          </Button>
        )}
      </div>

      {showFilters && (
        <Card className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label={t("items.category")}>
            {(id) => (
              <CategorySelect
                id={id}
                value={filters.category_id}
                onChange={(v) => update({ category_id: v })}
                emptyLabel={t("common.all")}
              />
            )}
          </Field>
          <Field label={t("items.location")}>
            {(id) => (
              <LocationSelect
                id={id}
                value={filters.location_id}
                onChange={(v) => update({ location_id: v })}
                emptyLabel={t("common.all")}
              />
            )}
          </Field>
          <Field label={t("items.status")}>
            {(id) => (
              <Select
                id={id}
                value={filters.status ?? ""}
                onChange={(e) => update({ status: e.target.value || null })}
              >
                <option value="">{t("common.all")}</option>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {t(`status.${s}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t("items.tags")}>
            {(id) => (
              <TagInput id={id} value={filters.tag ?? []} onChange={(v) => update({ tag: v })} />
            )}
          </Field>
          <div className="flex flex-wrap items-center gap-4 sm:col-span-2 lg:col-span-4">
            <Checkbox
              label={t("items.onlyUnplaced")}
              checked={!!filters.unplaced}
              onChange={(v) => update({ unplaced: v ? "1" : null })}
            />
            <Checkbox
              label={t("items.onlyLowStock")}
              checked={!!filters.low_stock}
              onChange={(v) => update({ low_stock: v ? "1" : null })}
            />
            <Checkbox
              label={t("items.onlyTrash")}
              checked={!!filters.trash}
              onChange={(v) => update({ trash: v ? "1" : null })}
            />
            {activeFilterCount > 0 && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setParams(new URLSearchParams(filters.q ? { q: filters.q } : {}))}
              >
                <X className="size-4" /> {t("items.clearFilters")}
              </Button>
            )}
          </div>
        </Card>
      )}

      {selected.size > 0 && canWrite && (
        <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 rounded-lg bg-brand-600 p-2 text-sm text-white shadow">
          <span className="px-2 font-medium">{t("items.selected", { count: selected.size })}</span>
          <Button size="sm" onClick={() => setBulkOpen(true)}>
            {t("items.bulk.actions")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="!text-white"
            onClick={() => setSelected(new Set())}
          >
            {t("common.cancel")}
          </Button>
        </div>
      )}

      {isPending ? (
        <Spinner />
      ) : isError ? (
        <p role="alert" className="text-red-600">
          {errorMessage(error)}
        </p>
      ) : data.items.length === 0 ? (
        <Card>
          <EmptyState
            title={activeFilterCount || filters.q ? t("items.noResults") : t("items.empty")}
            hint={activeFilterCount || filters.q ? undefined : t("items.emptyHint")}
            action={
              canWrite && !filters.trash && !(activeFilterCount || filters.q) ? (
                <Button variant="primary" onClick={() => setCreating(true)}>
                  {t("items.add")}
                </Button>
              ) : undefined
            }
          />
        </Card>
      ) : (
        <div className={clsx(isFetching && "opacity-70 transition-opacity")}>
          {/* Karty: mobil vždy, desktop dle přepínače */}
          <div
            className={clsx(
              "grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3",
              view === "table" && "md:hidden",
            )}
          >
            {data.items.map((item) => (
              <button
                key={item.id}
                onClick={() => openItem(item.id)}
                className="min-w-0 rounded-xl border border-slate-200 bg-white p-3 text-left hover:border-brand-500 dark:border-slate-800 dark:bg-slate-900"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="font-medium">{item.name}</span>
                  <Badge tone={STATUS_TONE[item.status]}>{t(`status.${item.status}`)}</Badge>
                </div>
                <div className="mt-1 truncate text-sm text-slate-500">
                  {item.placements.length ? placementSummary(item) : t("items.unplaced")}
                </div>
                <div className="mt-1 flex items-center justify-between text-xs text-slate-500">
                  <span>{item.category_path ?? t("items.noCategory")}</span>
                  <span className={item.is_low_stock ? "font-semibold text-amber-600" : ""}>
                    {formatQty(item.total_quantity, item.unit)}
                  </span>
                </div>
              </button>
            ))}
          </div>

          {view === "table" && (
            <div className="hidden overflow-x-auto rounded-xl border border-slate-200 bg-white md:block dark:border-slate-800 dark:bg-slate-900">
              <table className="w-full text-sm">
                <thead className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800">
                  {table.getHeaderGroups().map((hg) => (
                    <tr key={hg.id}>
                      {hg.headers.map((h) => {
                        const sortable = !!SORT_KEYS[h.column.id];
                        const active = filters.sort === SORT_KEYS[h.column.id];
                        return (
                          <th
                            key={h.id}
                            className="px-3 py-2 font-medium"
                            aria-sort={
                              active ? (filters.desc ? "descending" : "ascending") : undefined
                            }
                          >
                            {sortable ? (
                              <button
                                className="inline-flex items-center gap-1 uppercase"
                                onClick={() => toggleSort(h.column.id)}
                              >
                                {flexRender(h.column.columnDef.header, h.getContext())}
                                {active &&
                                  (filters.desc ? (
                                    <ArrowDown className="size-3" />
                                  ) : (
                                    <ArrowUp className="size-3" />
                                  ))}
                              </button>
                            ) : (
                              flexRender(h.column.columnDef.header, h.getContext())
                            )}
                          </th>
                        );
                      })}
                    </tr>
                  ))}
                </thead>
                <tbody>
                  {table.getRowModel().rows.map((row) => (
                    <tr
                      key={row.id}
                      tabIndex={0}
                      onClick={() => openItem(row.original.id)}
                      onKeyDown={(e) => e.key === "Enter" && openItem(row.original.id)}
                      className={clsx(
                        "cursor-pointer border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800/60 dark:hover:bg-slate-800/50",
                        openId === row.original.id && "bg-brand-50 dark:bg-brand-700/10",
                      )}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="max-w-xs px-3 py-2">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="flex items-center justify-between pt-3 text-sm text-slate-500">
            <span>{t("common.range", { from, to, total })}</span>
            <div className="flex gap-1">
              <Button
                size="sm"
                aria-label={t("common.prev")}
                disabled={filters.offset === 0}
                onClick={() => update({ offset: String(Math.max(0, filters.offset! - pageSize)) })}
              >
                <ChevronLeft className="size-4" />
              </Button>
              <Button
                size="sm"
                aria-label={t("common.next")}
                disabled={to >= total}
                onClick={() => update({ offset: String(filters.offset! + pageSize) })}
              >
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        </div>
      )}

      <Drawer open={!!openId} onClose={closeItem} title={<ItemTitle id={openId} />}>
        {openId && <ItemDetail id={openId} onClose={closeItem} />}
      </Drawer>

      <Modal open={creating} onClose={() => setCreating(false)} title={t("items.add")} wide>
        <ItemForm
          presetLocation={filters.location_id}
          presetCategory={filters.category_id}
          onCancel={() => setCreating(false)}
          onDone={(saved) => {
            setCreating(false);
            openItem(saved.id);
          }}
        />
      </Modal>

      <BulkDialog
        open={bulkOpen}
        ids={[...selected]}
        onClose={() => setBulkOpen(false)}
        onDone={() => setSelected(new Set())}
        trash={!!filters.trash}
      />
    </div>
  );
}

function ItemTitle({ id }: { id?: string }) {
  const { data } = useItem(id);
  return <h2 className="truncate text-lg font-semibold">{data?.name ?? "…"}</h2>;
}

function BulkDialog({
  open,
  ids,
  onClose,
  onDone,
  trash,
}: {
  open: boolean;
  ids: string[];
  onClose: () => void;
  onDone: () => void;
  trash: boolean;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const [action, setAction] = useState<
    "move" | "set_category" | "add_tags" | "set_status" | "delete"
  >("move");
  const [location, setLocation] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [status, setStatus] = useState<ItemStatus>("stored");
  const [error, setError] = useState<string | null>(null);

  const run = useApiMutation(() =>
    api_.bulk({ ids, action, location_id: location, category_id: category, tags, status }),
  );

  const valid =
    (action === "move" && location) ||
    action === "set_category" ||
    (action === "add_tags" && tags.length) ||
    action === "set_status" ||
    action === "delete";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("items.bulk.title", { count: ids.length })}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            variant={action === "delete" ? "danger" : "primary"}
            disabled={!valid || run.isPending}
            onClick={async () => {
              setError(null);
              try {
                const res = await run.mutateAsync(undefined);
                toast(
                  t("items.bulk.result", { ok: res.ok, failed: res.failed.length }),
                  res.failed.length ? "error" : "ok",
                );
                onDone();
                onClose();
              } catch (e) {
                setError(errorMessage(e));
              }
            }}
          >
            {t("common.confirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("items.bulk.action")}>
          {(id) => (
            <Select
              id={id}
              value={action}
              onChange={(e) => setAction(e.target.value as typeof action)}
            >
              <option value="move">{t("items.bulk.move")}</option>
              <option value="set_category">{t("items.bulk.setCategory")}</option>
              <option value="add_tags">{t("items.bulk.addTags")}</option>
              <option value="set_status">{t("items.bulk.setStatus")}</option>
              {!trash && <option value="delete">{t("items.bulk.delete")}</option>}
            </Select>
          )}
        </Field>
        {action === "move" && (
          <Field label={t("items.targetLocation")}>
            {(id) => (
              <LocationSelect
                id={id}
                value={location}
                onChange={setLocation}
                emptyLabel={t("items.chooseLocation")}
              />
            )}
          </Field>
        )}
        {action === "set_category" && (
          <Field label={t("items.category")}>
            {(id) => <CategorySelect id={id} value={category} onChange={setCategory} />}
          </Field>
        )}
        {action === "add_tags" && (
          <Field label={t("items.tags")}>
            {(id) => <TagInput id={id} value={tags} onChange={setTags} />}
          </Field>
        )}
        {action === "set_status" && (
          <Field label={t("items.status")}>
            {(id) => (
              <Select
                id={id}
                value={status}
                onChange={(e) => setStatus(e.target.value as ItemStatus)}
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {t(`status.${s}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
        {action === "delete" && <p className="text-sm">{t("items.bulk.deleteHint")}</p>}
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
