import { useTranslation } from "react-i18next";

import type { ItemFilters, LocationKind } from "../../api/types";
import { Checkbox, Chip, Field, Input, Select } from "../../components/ui";
import { LOCATION_KINDS } from "../../lib/format";

const CONDITIONS = ["new", "good", "worn", "broken"] as const;
const SORTS = [
  "relevance",
  "name",
  "label",
  "updated",
  "created",
  "price",
  "quantity",
  "warranty",
  "expires",
] as const;

type Patch = Record<string, string | string[] | null>;

/** Hodnoty rozšířených filtrů, které jsou právě zapnuté (počítá se do odznaku „Filtry“). */
export function advancedFilterCount(f: ItemFilters): number {
  return [
    f.location_kind?.length,
    f.brand,
    f.condition,
    f.has_photo !== undefined,
    f.no_category,
    f.min_price,
    f.max_price,
    f.purchased_after,
    f.purchased_before,
    f.min_qty,
    f.max_qty,
    f.created_after,
    f.updated_after,
    f.warranty_before,
    f.expires_before,
    f.expired,
    f.warranty_active,
  ].filter(Boolean).length;
}

/** Textové a číselné pole: změna se odešle až při opuštění pole nebo Enteru (bez zbytečných dotazů). */
function CommitInput({
  value,
  onCommit,
  ...rest
}: {
  value: string;
  onCommit: (v: string) => void;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  return (
    <Input
      key={value}
      defaultValue={value}
      onBlur={(e) => e.target.value !== value && onCommit(e.target.value.trim())}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      {...rest}
    />
  );
}

export default function AdvancedFilters({
  filters,
  update,
}: {
  filters: ItemFilters;
  update: (patch: Patch) => void;
}) {
  const { t } = useTranslation();
  const kinds = filters.location_kind ?? [];
  const toggleKind = (k: LocationKind) =>
    update({ location_kind: kinds.includes(k) ? kinds.filter((x) => x !== k) : [...kinds, k] });
  const date = (key: keyof ItemFilters, label: string) => (
    <Field label={label}>
      {(id) => (
        <Input
          id={id}
          type="date"
          value={(filters[key] as string | undefined) ?? ""}
          onChange={(e) => update({ [key]: e.target.value || null })}
        />
      )}
    </Field>
  );
  const num = (key: keyof ItemFilters, label: string, step = "any") => (
    <Field label={label}>
      {(id) => (
        <CommitInput
          id={id}
          type="number"
          min="0"
          step={step}
          inputMode="decimal"
          value={(filters[key] as string | undefined) ?? ""}
          onCommit={(v) => update({ [key]: v || null })}
        />
      )}
    </Field>
  );

  return (
    <div className="space-y-3 border-t border-slate-200 pt-3 sm:col-span-2 lg:col-span-4 dark:border-slate-800">
      <div>
        <div className="mb-1 text-sm font-medium">{t("items.adv.locationKind")}</div>
        <div className="flex flex-wrap gap-1" role="group" aria-label={t("items.adv.locationKind")}>
          {LOCATION_KINDS.map((k) => (
            <Chip key={k} active={kinds.includes(k)} onClick={() => toggleKind(k)}>
              {t(`kind.${k}`)}
            </Chip>
          ))}
        </div>
        <p className="mt-1 text-xs text-slate-500">{t("items.adv.locationKindHint")}</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label={t("items.brand")}>
          {(id) => (
            <CommitInput
              id={id}
              value={filters.brand ?? ""}
              onCommit={(v) => update({ brand: v || null })}
            />
          )}
        </Field>
        <Field label={t("items.condition")}>
          {(id) => (
            <Select
              id={id}
              value={filters.condition ?? ""}
              onChange={(e) => update({ condition: e.target.value || null })}
            >
              <option value="">{t("common.all")}</option>
              {CONDITIONS.map((c) => (
                <option key={c} value={c}>
                  {t(`condition.${c}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t("items.adv.photo")}>
          {(id) => (
            <Select
              id={id}
              value={filters.has_photo === undefined ? "" : filters.has_photo ? "1" : "0"}
              onChange={(e) => update({ has_photo: e.target.value || null })}
            >
              <option value="">{t("common.all")}</option>
              <option value="1">{t("items.adv.withPhoto")}</option>
              <option value="0">{t("items.adv.withoutPhoto")}</option>
            </Select>
          )}
        </Field>
        <div />
        {num("min_price", t("items.adv.priceFrom"))}
        {num("max_price", t("items.adv.priceTo"))}
        {num("min_qty", t("items.adv.qtyFrom"))}
        {num("max_qty", t("items.adv.qtyTo"))}
        {date("purchased_after", t("items.adv.purchasedFrom"))}
        {date("purchased_before", t("items.adv.purchasedTo"))}
        {date("created_after", t("items.adv.createdFrom"))}
        {date("updated_after", t("items.adv.updatedFrom"))}
        {date("warranty_before", t("items.adv.warrantyTo"))}
        {date("expires_before", t("items.adv.expiresTo"))}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Checkbox
          label={t("items.adv.noCategory")}
          checked={!!filters.no_category}
          onChange={(v) => update({ no_category: v ? "1" : null })}
        />
        <Checkbox
          label={t("items.adv.warrantyActive")}
          checked={!!filters.warranty_active}
          onChange={(v) => update({ warranty_active: v ? "1" : null })}
        />
        <Checkbox
          label={t("items.adv.expired")}
          checked={!!filters.expired}
          onChange={(v) => update({ expired: v ? "1" : null })}
        />
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("items.adv.sort")} className="min-w-48">
          {(id) => (
            <Select
              id={id}
              value={filters.sort ?? "name"}
              onChange={(e) => update({ sort: e.target.value })}
            >
              {SORTS.map((s) => (
                <option key={s} value={s} disabled={s === "relevance" && !filters.q}>
                  {t(`items.sortBy.${s}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Checkbox
          label={t("items.adv.descending")}
          checked={!!filters.desc}
          onChange={(v) => update({ desc: v ? "1" : null })}
        />
      </div>
    </div>
  );
}
