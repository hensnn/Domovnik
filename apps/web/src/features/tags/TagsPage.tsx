import { GitMerge, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api_, useApiMutation, useTags } from "../../api/hooks";
import type { Tag } from "../../api/types";
import { TagBadge } from "../../components/TagBadge";
import {
  Button,
  Card,
  Checkbox,
  EmptyState,
  Field,
  IconButton,
  Input,
  Modal,
  Select,
  Spinner,
  errorMessage,
  useToast,
} from "../../components/ui";
import { useAuth } from "../auth/AuthProvider";

const DEFAULT_COLOR = "#64748b";

type Dialog =
  | { kind: "edit"; tag: Tag }
  | { kind: "merge"; tag: Tag }
  | { kind: "delete"; tag: Tag }
  | { kind: "unused" }
  | null;

/** Správa tagů (štítků věcí): přidání, přejmenování, barva, sloučení duplicit, smazání. */
export default function TagsPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const { can } = useAuth();
  const canWrite = can("items:write");
  const { data, isPending, isError, error } = useTags();
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<"name" | "count">("name");
  const [onlyUnused, setOnlyUnused] = useState(false);
  const [dialog, setDialog] = useState<Dialog>(null);

  const unused = useMemo(() => (data ?? []).filter((x) => x.item_count === 0), [data]);
  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const list = (data ?? []).filter(
      (x) => (!needle || x.name.toLowerCase().includes(needle)) && (!onlyUnused || !x.item_count),
    );
    return sort === "count"
      ? [...list].sort((a, b) => b.item_count - a.item_count || a.name.localeCompare(b.name, "cs"))
      : list; // API vrací seřazeno podle názvu
  }, [data, filter, sort, onlyUnused]);

  return (
    <div className="mx-auto max-w-3xl space-y-3 p-3 md:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-xl font-bold">
          {t("tags.title")}
          <span className="ml-2 text-sm font-normal text-slate-500">{data?.length ?? 0}</span>
        </h1>
      </div>
      <p className="text-sm text-slate-500">{t("tags.intro")}</p>

      {canWrite && <AddTag />}

      <Card className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-40 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={t("tags.filter")}
              aria-label={t("tags.filter")}
              className="pl-9"
            />
          </div>
          <Select
            aria-label={t("tags.sort")}
            value={sort}
            onChange={(e) => setSort(e.target.value as "name" | "count")}
            className="!w-auto"
          >
            <option value="name">{t("tags.sortName")}</option>
            <option value="count">{t("tags.sortCount")}</option>
          </Select>
          <Checkbox label={t("tags.onlyUnused")} checked={onlyUnused} onChange={setOnlyUnused} />
          {canWrite && unused.length > 0 && (
            <Button size="sm" onClick={() => setDialog({ kind: "unused" })}>
              <Trash2 className="size-4" /> {t("tags.deleteUnused", { count: unused.length })}
            </Button>
          )}
        </div>

        {isPending ? (
          <Spinner />
        ) : isError ? (
          <p role="alert" className="text-red-600">
            {errorMessage(error)}
          </p>
        ) : shown.length === 0 ? (
          <EmptyState
            title={data?.length ? t("tags.noMatch") : t("tags.empty")}
            hint={data?.length ? undefined : t("tags.emptyHint")}
          />
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {shown.map((tag) => (
              <li key={tag.id} className="flex items-center gap-2 py-2">
                <div className="min-w-0 flex-1">
                  <TagBadge name={tag.name} color={tag.color} />
                </div>
                <Link
                  to={`/items?tag=${encodeURIComponent(tag.name)}`}
                  className="text-sm text-brand-700 hover:underline dark:text-brand-100"
                >
                  {t("tags.itemCount", { count: tag.item_count })}
                </Link>
                {canWrite && (
                  <div className="flex shrink-0">
                    <IconButton
                      label={t("tags.edit", { name: tag.name })}
                      onClick={() => setDialog({ kind: "edit", tag })}
                    >
                      <Pencil className="size-4" />
                    </IconButton>
                    <IconButton
                      label={t("tags.merge", { name: tag.name })}
                      disabled={(data?.length ?? 0) < 2}
                      onClick={() => setDialog({ kind: "merge", tag })}
                    >
                      <GitMerge className="size-4" />
                    </IconButton>
                    <IconButton
                      label={t("tags.delete", { name: tag.name })}
                      onClick={() => setDialog({ kind: "delete", tag })}
                    >
                      <Trash2 className="size-4" />
                    </IconButton>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {dialog?.kind === "edit" && (
        <EditDialog tag={dialog.tag} onClose={() => setDialog(null)} toast={toast} />
      )}
      {dialog?.kind === "merge" && (
        <MergeDialog
          tag={dialog.tag}
          all={data ?? []}
          onClose={() => setDialog(null)}
          toast={toast}
        />
      )}
      {dialog?.kind === "delete" && (
        <DeleteDialog tag={dialog.tag} onClose={() => setDialog(null)} toast={toast} />
      )}
      {dialog?.kind === "unused" && (
        <UnusedDialog tags={unused} onClose={() => setDialog(null)} toast={toast} />
      )}
    </div>
  );
}

type ToastFn = ReturnType<typeof useToast>;

function ColorField({
  color,
  onChange,
}: {
  color: string | null;
  onChange: (c: string | null) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-2">
      <input
        type="color"
        aria-label={t("tags.color")}
        value={color ?? DEFAULT_COLOR}
        onChange={(e) => onChange(e.target.value)}
        className="size-10 cursor-pointer rounded-lg border border-slate-300 bg-white p-1 dark:border-slate-700 dark:bg-slate-900"
      />
      {color ? (
        <Button size="sm" variant="ghost" onClick={() => onChange(null)}>
          {t("tags.noColor")}
        </Button>
      ) : (
        <span className="text-xs text-slate-500">{t("tags.noColorSet")}</span>
      )}
    </div>
  );
}

function AddTag() {
  const { t } = useTranslation();
  const toast = useToast();
  const [name, setName] = useState("");
  const [color, setColor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const create = useApiMutation(() => api_.createTag({ name: name.trim(), color }), {
    onSuccess: () => {
      toast(t("tags.created"));
      setName("");
      setColor(null);
    },
  });
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await create.mutateAsync(undefined);
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  return (
    <Card>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <Field label={t("tags.newName")} className="min-w-48 flex-1">
          {(id) => (
            <Input
              id={id}
              value={name}
              maxLength={100}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("tags.newPlaceholder")}
            />
          )}
        </Field>
        <ColorField color={color} onChange={setColor} />
        <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>
          <Plus className="size-4" /> {t("tags.add")}
        </Button>
      </form>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {error}
        </p>
      )}
    </Card>
  );
}

function EditDialog({ tag, onClose, toast }: { tag: Tag; onClose: () => void; toast: ToastFn }) {
  const { t } = useTranslation();
  const [name, setName] = useState(tag.name);
  const [color, setColor] = useState<string | null>(tag.color);
  const [error, setError] = useState<string | null>(null);
  const save = useApiMutation(
    () => {
      const body: { name?: string; color?: string | null } = {};
      if (name.trim() !== tag.name) body.name = name.trim();
      if (color !== tag.color) body.color = color;
      return api_.updateTag(tag.id, body);
    },
    {
      onSuccess: () => {
        toast(t("common.saved"));
        onClose();
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
  const changed = name.trim() !== tag.name || color !== tag.color;
  return (
    <Modal open onClose={onClose} title={t("tags.editTitle", { name: tag.name })}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t("tags.name")}>
          {(id) => (
            <Input
              id={id}
              autoFocus
              required
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("tags.color")}>
          {() => <ColorField color={color} onChange={setColor} />}
        </Field>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            type="submit"
            variant="primary"
            disabled={!name.trim() || !changed || save.isPending}
          >
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function MergeDialog({
  tag,
  all,
  onClose,
  toast,
}: {
  tag: Tag;
  all: Tag[];
  onClose: () => void;
  toast: ToastFn;
}) {
  const { t } = useTranslation();
  const others = all.filter((x) => x.id !== tag.id);
  const [target, setTarget] = useState("");
  const [error, setError] = useState<string | null>(null);
  const merge = useApiMutation(() => api_.mergeTag(tag.id, target), {
    onSuccess: () => {
      toast(t("tags.merged"));
      onClose();
    },
  });
  const targetTag = others.find((x) => x.id === target);
  return (
    <Modal
      open
      onClose={onClose}
      title={t("tags.mergeTitle", { name: tag.name })}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            variant="primary"
            disabled={!target || merge.isPending}
            onClick={async () => {
              setError(null);
              try {
                await merge.mutateAsync(undefined);
              } catch (err) {
                setError(errorMessage(err));
              }
            }}
          >
            {t("tags.mergeDo")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm">{t("tags.mergeHint", { count: tag.item_count, name: tag.name })}</p>
        <Field label={t("tags.mergeTarget")}>
          {(id) => (
            <Select id={id} value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">{t("tags.chooseTarget")}</option>
              {others.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name} ({x.item_count})
                </option>
              ))}
            </Select>
          )}
        </Field>
        {targetTag && (
          <p className="text-sm text-slate-500">
            {t("tags.mergeResult", { source: tag.name, target: targetTag.name })}
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}

function DeleteDialog({ tag, onClose, toast }: { tag: Tag; onClose: () => void; toast: ToastFn }) {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);
  const remove = useApiMutation(() => api_.deleteTag(tag.id), {
    onSuccess: () => {
      toast(t("common.done"));
      onClose();
    },
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={t("tags.deleteTitle", { name: tag.name })}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            variant="danger"
            disabled={remove.isPending}
            onClick={async () => {
              setError(null);
              try {
                await remove.mutateAsync(undefined);
              } catch (err) {
                setError(errorMessage(err));
              }
            }}
          >
            {t("common.delete")}
          </Button>
        </>
      }
    >
      <p className="text-sm">{t("tags.deleteHint", { count: tag.item_count })}</p>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {error}
        </p>
      )}
    </Modal>
  );
}

function UnusedDialog({
  tags,
  onClose,
  toast,
}: {
  tags: Tag[];
  onClose: () => void;
  toast: ToastFn;
}) {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);
  const run = useApiMutation(
    async () => {
      for (const tag of tags) await api_.deleteTag(tag.id);
    },
    {
      onSuccess: () => {
        toast(t("common.done"));
        onClose();
      },
    },
  );
  return (
    <Modal
      open
      onClose={onClose}
      title={t("tags.deleteUnusedTitle", { count: tags.length })}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            variant="danger"
            disabled={run.isPending}
            onClick={async () => {
              setError(null);
              try {
                await run.mutateAsync(undefined);
              } catch (err) {
                setError(errorMessage(err));
              }
            }}
          >
            {t("common.delete")}
          </Button>
        </>
      }
    >
      <p className="text-sm">{t("tags.deleteUnusedHint")}</p>
      <p className="mt-2 text-sm text-slate-500">{tags.map((x) => x.name).join(", ")}</p>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {error}
        </p>
      )}
    </Modal>
  );
}
