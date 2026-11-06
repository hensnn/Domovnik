import { ChevronDown } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api_, useApiMutation } from "../../api/hooks";
import type { Item, ItemStatus } from "../../api/types";
import { CategorySelect, LocationSelect, TagInput } from "../../components/Pickers";
import {
  Button,
  Checkbox,
  Field,
  Input,
  Select,
  Textarea,
  errorMessage,
  useToast,
} from "../../components/ui";

const STATUSES: ItemStatus[] = ["stored", "in_use", "lent", "repair", "discarded", "sold", "lost"];
const CONDITIONS = ["", "new", "good", "worn", "broken"];

interface FormState {
  name: string;
  aliases: string;
  category_id: string | null;
  tags: string[];
  status: ItemStatus;
  description: string;
  notes: string;
  is_consumable: boolean;
  unit: string;
  min_quantity: string;
  home_location_id: string | null;
  brand: string;
  model: string;
  serial_no: string;
  ean: string;
  condition: string;
  purchase_date: string;
  purchase_price: string;
  purchase_place: string;
  warranty_until: string;
  expires_at: string;
  est_value: string;
  // jen při vytvoření
  location_id: string | null;
  quantity: string;
}

function initial(
  item?: Item,
  presetLocation?: string | null,
  presetCategory?: string | null,
): FormState {
  return {
    name: item?.name ?? "",
    aliases: item?.aliases.join(", ") ?? "",
    category_id: item?.category_id ?? presetCategory ?? null,
    tags: item?.tags ?? [],
    status: item?.status ?? "stored",
    description: item?.description ?? "",
    notes: item?.notes ?? "",
    is_consumable: item?.is_consumable ?? false,
    unit: item?.unit ?? "ks",
    min_quantity: item?.min_quantity ?? "",
    home_location_id: item?.home_location_id ?? null,
    brand: item?.brand ?? "",
    model: item?.model ?? "",
    serial_no: item?.serial_no ?? "",
    ean: item?.ean ?? "",
    condition: item?.condition ?? "",
    purchase_date: item?.purchase_date ?? "",
    purchase_price: item?.purchase_price ?? "",
    purchase_place: item?.purchase_place ?? "",
    warranty_until: item?.warranty_until ?? "",
    expires_at: item?.expires_at ?? "",
    est_value: item?.est_value ?? "",
    location_id: presetLocation ?? null,
    quantity: "1",
  };
}

const orNull = (s: string) => (s.trim() === "" ? null : s.trim());

/** Formulář pro vytvoření i úpravu věci. */
export default function ItemForm({
  item,
  presetLocation,
  presetCategory,
  onDone,
  onCancel,
}: {
  item?: Item;
  presetLocation?: string | null;
  presetCategory?: string | null;
  onDone: (saved: Item) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const [f, setF] = useState<FormState>(() => initial(item, presetLocation, presetCategory));
  const [more, setMore] = useState(!!item);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }));

  const save = useApiMutation(
    async () => {
      const common = {
        name: f.name.trim(),
        aliases: f.aliases
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        category_id: f.category_id,
        tags: f.tags,
        status: f.status,
        description: orNull(f.description),
        notes: orNull(f.notes),
        is_consumable: f.is_consumable,
        unit: f.unit.trim() || "ks",
        min_quantity: orNull(f.min_quantity),
        home_location_id: f.home_location_id,
        brand: orNull(f.brand),
        model: orNull(f.model),
        serial_no: orNull(f.serial_no),
        ean: orNull(f.ean),
        condition: orNull(f.condition),
        purchase_date: orNull(f.purchase_date),
        purchase_price: orNull(f.purchase_price),
        purchase_place: orNull(f.purchase_place),
        warranty_until: orNull(f.warranty_until),
        expires_at: orNull(f.expires_at),
        est_value: orNull(f.est_value),
      };
      if (item) return api_.updateItem(item.id, common, item.version);
      return api_.createItem({
        ...common,
        placements: f.location_id
          ? [{ location_id: f.location_id, quantity: Number(f.quantity.replace(",", ".")) || 1 }]
          : [],
      });
    },
    {
      onSuccess: (saved) => {
        toast(item ? t("items.saved") : t("items.created"));
        onDone(saved as Item);
      },
    },
  );

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await save.mutateAsync(undefined);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label={t("items.name")}>
        {(id) => (
          <Input
            id={id}
            autoFocus
            required
            value={f.name}
            onChange={(e) => set("name", e.target.value)}
          />
        )}
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("items.category")}>
          {(id) => (
            <CategorySelect id={id} value={f.category_id} onChange={(v) => set("category_id", v)} />
          )}
        </Field>
        <Field label={t("items.status")}>
          {(id) => (
            <Select
              id={id}
              value={f.status}
              onChange={(e) => set("status", e.target.value as ItemStatus)}
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`status.${s}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>

      {!item && (
        <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
          <Field label={t("items.location")} hint={t("items.locationHint")}>
            {(id) => (
              <LocationSelect
                id={id}
                value={f.location_id}
                onChange={(v) => set("location_id", v)}
                emptyLabel={t("items.unplaced")}
              />
            )}
          </Field>
          <Field label={t("items.quantity")}>
            {(id) => (
              <Input
                id={id}
                inputMode="decimal"
                value={f.quantity}
                onChange={(e) => set("quantity", e.target.value)}
                disabled={!f.location_id}
              />
            )}
          </Field>
        </div>
      )}

      <Field label={t("items.tags")}>
        {(id) => <TagInput id={id} value={f.tags} onChange={(v) => set("tags", v)} />}
      </Field>
      <Field label={t("items.notes")}>
        {(id) => (
          <Textarea id={id} value={f.notes} onChange={(e) => set("notes", e.target.value)} />
        )}
      </Field>

      <button
        type="button"
        onClick={() => setMore((m) => !m)}
        className="flex items-center gap-1 text-sm font-medium text-brand-700 dark:text-brand-100"
        aria-expanded={more}
      >
        <ChevronDown className={`size-4 transition-transform ${more ? "rotate-180" : ""}`} />
        {t("items.moreDetails")}
      </button>

      {more && (
        <div className="space-y-4 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
          <Field label={t("items.aliases")} hint={t("items.aliasesHint")}>
            {(id) => (
              <Input id={id} value={f.aliases} onChange={(e) => set("aliases", e.target.value)} />
            )}
          </Field>
          <Field label={t("items.description")}>
            {(id) => (
              <Textarea
                id={id}
                value={f.description}
                onChange={(e) => set("description", e.target.value)}
              />
            )}
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("items.brand")}>
              {(id) => (
                <Input id={id} value={f.brand} onChange={(e) => set("brand", e.target.value)} />
              )}
            </Field>
            <Field label={t("items.model")}>
              {(id) => (
                <Input id={id} value={f.model} onChange={(e) => set("model", e.target.value)} />
              )}
            </Field>
            <Field label={t("items.serial")}>
              {(id) => (
                <Input
                  id={id}
                  value={f.serial_no}
                  onChange={(e) => set("serial_no", e.target.value)}
                />
              )}
            </Field>
            <Field label={t("items.ean")}>
              {(id) => <Input id={id} value={f.ean} onChange={(e) => set("ean", e.target.value)} />}
            </Field>
            <Field label={t("items.condition")}>
              {(id) => (
                <Select
                  id={id}
                  value={f.condition}
                  onChange={(e) => set("condition", e.target.value)}
                >
                  {CONDITIONS.map((c) => (
                    <option key={c} value={c}>
                      {c ? t(`condition.${c}`) : t("common.none")}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t("items.homeLocation")} hint={t("items.homeLocationHint")}>
              {(id) => (
                <LocationSelect
                  id={id}
                  value={f.home_location_id}
                  onChange={(v) => set("home_location_id", v)}
                />
              )}
            </Field>
          </div>
          <div className="flex flex-wrap items-end gap-4">
            <Checkbox
              label={t("items.consumable")}
              checked={f.is_consumable}
              onChange={(v) => set("is_consumable", v)}
            />
            <Field label={t("items.unit")} className="w-24">
              {(id) => (
                <Input id={id} value={f.unit} onChange={(e) => set("unit", e.target.value)} />
              )}
            </Field>
            <Field
              label={t("items.minQuantity")}
              hint={t("items.minQuantityHint")}
              className="w-40"
            >
              {(id) => (
                <Input
                  id={id}
                  inputMode="decimal"
                  value={f.min_quantity}
                  onChange={(e) => set("min_quantity", e.target.value)}
                />
              )}
            </Field>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("items.purchaseDate")}>
              {(id) => (
                <Input
                  id={id}
                  type="date"
                  value={f.purchase_date}
                  onChange={(e) => set("purchase_date", e.target.value)}
                />
              )}
            </Field>
            <Field label={t("items.purchasePrice")}>
              {(id) => (
                <Input
                  id={id}
                  inputMode="decimal"
                  value={f.purchase_price}
                  onChange={(e) => set("purchase_price", e.target.value)}
                />
              )}
            </Field>
            <Field label={t("items.purchasePlace")}>
              {(id) => (
                <Input
                  id={id}
                  value={f.purchase_place}
                  onChange={(e) => set("purchase_place", e.target.value)}
                />
              )}
            </Field>
            <Field label={t("items.estValue")}>
              {(id) => (
                <Input
                  id={id}
                  inputMode="decimal"
                  value={f.est_value}
                  onChange={(e) => set("est_value", e.target.value)}
                />
              )}
            </Field>
            <Field label={t("items.warranty")}>
              {(id) => (
                <Input
                  id={id}
                  type="date"
                  value={f.warranty_until}
                  onChange={(e) => set("warranty_until", e.target.value)}
                />
              )}
            </Field>
            <Field label={t("items.expires")}>
              {(id) => (
                <Input
                  id={id}
                  type="date"
                  value={f.expires_at}
                  onChange={(e) => set("expires_at", e.target.value)}
                />
              )}
            </Field>
          </div>
        </div>
      )}

      {error && (
        <p
          role="alert"
          className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
        >
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button onClick={onCancel}>{t("common.cancel")}</Button>
        <Button type="submit" variant="primary" disabled={save.isPending || !f.name.trim()}>
          {item ? t("common.save") : t("items.create")}
        </Button>
      </div>
    </form>
  );
}
