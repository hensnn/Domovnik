import { ArrowRightLeft, Edit3, MapPin, Minus, Plus, RotateCcw, Trash2 } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { api_, useApiMutation, useItem, useItemMovements, useLocations } from "../../api/hooks";
import type { Item, Placement } from "../../api/types";
import { LocationSelect } from "../../components/Pickers";
import FileGallery from "../files/FileGallery";
import {
  Badge,
  Button,
  Field,
  Input,
  Modal,
  Spinner,
  errorMessage,
  useToast,
} from "../../components/ui";
import { STATUS_TONE, formatDate, formatDateTime, formatMoney, formatQty } from "../../lib/format";
import { useAuth } from "../auth/AuthProvider";
import ItemForm from "./ItemForm";

export default function ItemDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const { can } = useAuth();
  const { data: item, isPending, isError, error } = useItem(id);
  const [editing, setEditing] = useState(false);
  const [tab, setTab] = useState<"info" | "history">("info");
  const [dialog, setDialog] = useState<null | {
    kind: "move" | "adjust" | "remove" | "add";
    placement?: Placement;
  }>(null);
  const canWrite = can("items:write");

  const del = useApiMutation(() => api_.deleteItem(id), {
    onSuccess: () => {
      toast(t("items.trashed"));
      onClose();
    },
  });
  const restore = useApiMutation(() => api_.restoreItem(id), {
    onSuccess: () => toast(t("items.restored")),
  });

  if (isPending) return <Spinner />;
  if (isError || !item) return <p className="p-4 text-red-600">{errorMessage(error)}</p>;

  if (editing) {
    return (
      <div className="p-4">
        <ItemForm item={item} onDone={() => setEditing(false)} onCancel={() => setEditing(false)} />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-3 border-b border-slate-200 p-4 dark:border-slate-800">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={STATUS_TONE[item.status]}>{t(`status.${item.status}`)}</Badge>
          {item.is_low_stock && <Badge tone="amber">{t("items.lowStock")}</Badge>}
          {item.deleted_at && <Badge tone="red">{t("items.inTrash")}</Badge>}
          <span className="font-mono text-xs text-slate-500">{item.label_code}</span>
        </div>
        <p className="text-sm text-slate-500">
          {item.category_path ?? t("items.noCategory")} · {t("items.total")}:{" "}
          <strong className="text-slate-900 dark:text-slate-100">
            {formatQty(item.total_quantity, item.unit)}
          </strong>
        </p>
        {canWrite && (
          <div className="flex flex-wrap gap-2">
            {item.deleted_at ? (
              <Button size="sm" onClick={() => restore.mutate(undefined)}>
                <RotateCcw className="size-4" /> {t("items.restore")}
              </Button>
            ) : (
              <>
                <Button size="sm" onClick={() => setEditing(true)}>
                  <Edit3 className="size-4" /> {t("common.edit")}
                </Button>
                <Button size="sm" onClick={() => del.mutate(undefined)} disabled={del.isPending}>
                  <Trash2 className="size-4" /> {t("items.toTrash")}
                </Button>
              </>
            )}
          </div>
        )}
        <div role="tablist" className="flex gap-4 text-sm">
          {(["info", "history"] as const).map((k) => (
            <button
              key={k}
              role="tab"
              aria-selected={tab === k}
              onClick={() => setTab(k)}
              className={`border-b-2 pb-1 font-medium ${tab === k ? "border-brand-600 text-brand-700 dark:text-brand-100" : "border-transparent text-slate-500"}`}
            >
              {t(`items.tab.${k}`)}
            </button>
          ))}
        </div>
      </div>

      {tab === "history" ? (
        <History id={id} />
      ) : (
        <div className="space-y-6 p-4">
          <FileGallery kind="item" id={item.id} canWrite={canWrite && !item.deleted_at} />

          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="font-semibold">{t("items.whereIs")}</h3>
              {canWrite && !item.deleted_at && (
                <Button size="sm" onClick={() => setDialog({ kind: "add" })}>
                  <Plus className="size-4" /> {t("items.addPlacement")}
                </Button>
              )}
            </div>
            {item.placements.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-300 p-3 text-sm text-slate-500 dark:border-slate-700">
                {t("items.unplacedHint")}
              </p>
            ) : (
              <ul className="space-y-2">
                {item.placements.map((p) => (
                  <li
                    key={p.location_id}
                    className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 p-3 dark:border-slate-800"
                  >
                    <MapPin className="size-4 text-brand-600" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{p.location_path}</div>
                      <div className="text-xs text-slate-500">
                        {formatQty(p.quantity, item.unit)} · {p.location_label}
                      </div>
                    </div>
                    {canWrite && !item.deleted_at && (
                      <div className="flex gap-1">
                        <Button
                          size="sm"
                          aria-label={t("items.move")}
                          onClick={() => setDialog({ kind: "move", placement: p })}
                        >
                          <ArrowRightLeft className="size-4" />
                        </Button>
                        <Button
                          size="sm"
                          aria-label={t("items.adjust")}
                          onClick={() => setDialog({ kind: "adjust", placement: p })}
                        >
                          <Edit3 className="size-4" />
                        </Button>
                        <Button
                          size="sm"
                          aria-label={t("items.remove")}
                          onClick={() => setDialog({ kind: "remove", placement: p })}
                        >
                          <Minus className="size-4" />
                        </Button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <Details item={item} />
        </div>
      )}

      {dialog && <PlacementDialog item={item} dialog={dialog} onClose={() => setDialog(null)} />}
    </div>
  );
}

function Details({ item }: { item: Item }) {
  const { t } = useTranslation();
  const rows: [string, ReactNode][] = [
    [t("items.brand"), item.brand],
    [t("items.model"), item.model],
    [t("items.serial"), item.serial_no],
    [t("items.ean"), item.ean],
    [t("items.condition"), item.condition ? t(`condition.${item.condition}`) : null],
    [
      t("items.homeLocation"),
      item.home_location_id ? <HomeName id={item.home_location_id} /> : null,
    ],
    [t("items.purchaseDate"), item.purchase_date ? formatDate(item.purchase_date) : null],
    [
      t("items.purchasePrice"),
      item.purchase_price ? formatMoney(item.purchase_price, item.currency) : null,
    ],
    [t("items.purchasePlace"), item.purchase_place],
    [t("items.warranty"), item.warranty_until ? formatDate(item.warranty_until) : null],
    [t("items.expires"), item.expires_at ? formatDate(item.expires_at) : null],
    [t("items.estValue"), item.est_value ? formatMoney(item.est_value, item.currency) : null],
    [t("items.minQuantity"), item.min_quantity ? formatQty(item.min_quantity, item.unit) : null],
    [t("items.aliases"), item.aliases.length ? item.aliases.join(", ") : null],
  ];
  const filled = rows.filter(([, v]) => v);
  return (
    <>
      {item.tags.length > 0 && (
        <section>
          <h3 className="mb-2 font-semibold">{t("items.tags")}</h3>
          <div className="flex flex-wrap gap-1.5">
            {item.tags.map((tag) => (
              <Badge key={tag}>{tag}</Badge>
            ))}
          </div>
        </section>
      )}
      {(item.description || item.notes) && (
        <section className="space-y-2 text-sm">
          {item.description && <p className="whitespace-pre-wrap">{item.description}</p>}
          {item.notes && (
            <p className="whitespace-pre-wrap rounded-lg bg-amber-50 p-3 dark:bg-amber-950/40">
              {item.notes}
            </p>
          )}
        </section>
      )}
      {filled.length > 0 && (
        <section>
          <h3 className="mb-2 font-semibold">{t("items.details")}</h3>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
            {filled.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-slate-500">{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}
      <p className="text-xs text-slate-400">
        {t("items.created")} {formatDateTime(item.created_at)} · {t("items.updated")}{" "}
        {formatDateTime(item.updated_at)}
      </p>
    </>
  );
}

function HomeName({ id }: { id: string }) {
  const { data = [] } = useLocations();
  return <>{data.find((l) => l.id === id)?.full_name ?? "…"}</>;
}

function History({ id }: { id: string }) {
  const { t } = useTranslation();
  const { data, isPending } = useItemMovements(id);
  const { data: locs = [] } = useLocations(true);
  const name = (lid: string | null) => locs.find((l) => l.id === lid)?.full_name ?? "–";
  if (isPending) return <Spinner />;
  if (!data?.length) return <p className="p-4 text-sm text-slate-500">{t("items.noHistory")}</p>;
  return (
    <ul className="divide-y divide-slate-200 text-sm dark:divide-slate-800">
      {data.map((m) => (
        <li key={m.id} className="space-y-0.5 px-4 py-3">
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium">{t(`movement.${m.kind}`)}</span>
            <span className="text-xs text-slate-500">{formatDateTime(m.moved_at)}</span>
          </div>
          <div className="text-slate-600 dark:text-slate-400">
            {m.from_location_id && <>{name(m.from_location_id)} → </>}
            {m.to_location_id ? name(m.to_location_id) : null}
            {m.quantity && <span> · {formatQty(m.quantity)}</span>}
          </div>
          <div className="text-xs text-slate-400">
            {t(`source.${m.source}`, { defaultValue: m.source })}
            {m.note ? ` · ${m.note}` : ""}
          </div>
        </li>
      ))}
    </ul>
  );
}

function PlacementDialog({
  item,
  dialog,
  onClose,
}: {
  item: Item;
  dialog: { kind: "move" | "adjust" | "remove" | "add"; placement?: Placement };
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const p = dialog.placement;
  const [target, setTarget] = useState<string | null>(null);
  const [qty, setQty] = useState(
    dialog.kind === "adjust" ? (p?.quantity ?? "1") : dialog.kind === "add" ? "1" : "",
  );
  const [error, setError] = useState<string | null>(null);

  const num = (s: string) => Number(s.replace(",", "."));
  const run = useApiMutation(
    async () => {
      if (dialog.kind === "move")
        return api_.moveItem(item.id, {
          from_location_id: p!.location_id,
          to_location_id: target,
          quantity: qty ? num(qty) : null,
        });
      if (dialog.kind === "add")
        return api_.placeItem(item.id, { location_id: target, quantity: num(qty) || 1 });
      if (dialog.kind === "adjust")
        return api_.adjustItem(item.id, { location_id: p!.location_id, quantity: num(qty) });
      return api_.removeItem(item.id, {
        location_id: p!.location_id,
        quantity: qty ? num(qty) : null,
      });
    },
    {
      onSuccess: () => {
        toast(t("common.done"));
        onClose();
      },
    },
  );

  const needsTarget = dialog.kind === "move" || dialog.kind === "add";
  const valid = (!needsTarget || target) && (dialog.kind !== "adjust" || qty !== "");

  return (
    <Modal
      open
      onClose={onClose}
      title={t(`items.dialog.${dialog.kind}`)}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            variant="primary"
            disabled={!valid || run.isPending}
            onClick={async () => {
              setError(null);
              try {
                await run.mutateAsync(undefined);
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
        {p && (
          <p className="text-sm text-slate-500">
            {p.location_path} · {formatQty(p.quantity, item.unit)}
          </p>
        )}
        {needsTarget && (
          <Field label={t("items.targetLocation")}>
            {(id) => (
              <LocationSelect
                id={id}
                value={target}
                onChange={setTarget}
                exclude={dialog.kind === "move" ? undefined : undefined}
                emptyLabel={t("items.chooseLocation")}
              />
            )}
          </Field>
        )}
        <Field
          label={t(dialog.kind === "adjust" ? "items.newQuantity" : "items.quantity")}
          hint={
            dialog.kind === "move" || dialog.kind === "remove"
              ? t("items.emptyMeansAll")
              : undefined
          }
        >
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
