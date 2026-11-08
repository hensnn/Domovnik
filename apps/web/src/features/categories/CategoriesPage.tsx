import clsx from "clsx";
import { ChevronDown, ChevronRight, Edit3, GitMerge, Plus, Sparkles, Trash2 } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api_, useApiMutation, useCategories, useTags } from "../../api/hooks";
import type { Category } from "../../api/types";
import { CategorySelect } from "../../components/Pickers";
import { TagBadge } from "../../components/TagBadge";
import {
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  Modal,
  Spinner,
  Textarea,
  errorMessage,
  useToast,
} from "../../components/ui";
import { type TreeNode, buildTree } from "../../lib/format";
import AssistantDrawer from "../assistant/AssistantDrawer";
import { useAuth } from "../auth/AuthProvider";

export default function CategoriesPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const { data, isPending } = useCategories();
  const tags = useTags();
  const tree = useMemo(() => buildTree(data ?? []), [data]);
  const [form, setForm] = useState<null | { edit?: Category; parent?: string | null }>(null);
  const [merge, setMerge] = useState<Category | null>(null);
  const [assistOpen, setAssistOpen] = useState(false);
  const canWrite = can("items:write");

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-3 md:p-5">
      <div className="flex items-center gap-2">
        <h1 className="mr-auto text-xl font-bold">{t("nav.categories")}</h1>
        {canWrite && (
          <>
            <Button size="sm" onClick={() => setAssistOpen(true)}>
              <Sparkles className="size-4" /> {t("nav.assistant")}
            </Button>
            <Button variant="primary" size="sm" onClick={() => setForm({ parent: null })}>
              <Plus className="size-4" /> {t("categories.add")}
            </Button>
          </>
        )}
      </div>
      <Card className="!p-2">
        {isPending ? (
          <Spinner />
        ) : tree.length === 0 ? (
          <EmptyState title={t("categories.empty")} hint={t("categories.emptyHint")} />
        ) : (
          <ul>
            {tree.map((n) => (
              <Row
                key={n.node.id}
                n={n}
                depth={0}
                canWrite={canWrite}
                onEdit={(c) => setForm({ edit: c })}
                onAdd={(p) => setForm({ parent: p })}
                onMerge={setMerge}
              />
            ))}
          </ul>
        )}
      </Card>

      <Card className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-semibold">{t("categories.tags")}</h2>
          <Link to="/tags" className="text-sm text-brand-700 hover:underline dark:text-brand-100">
            {t("categories.manageTags")}
          </Link>
        </div>
        {tags.data?.length ? (
          <div className="flex flex-wrap gap-2">
            {tags.data.map((tg) => (
              <Link key={tg.id} to={`/items?tag=${encodeURIComponent(tg.name)}`}>
                <TagBadge name={`${tg.name} · ${tg.item_count}`} color={tg.color} />
              </Link>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-500">{t("categories.noTags")}</p>
        )}
      </Card>

      {form && (
        <CategoryFormModal
          {...form}
          onClose={() => setForm(null)}
          onAssist={() => {
            setForm(null);
            setAssistOpen(true);
          }}
        />
      )}
      <AssistantDrawer
        open={assistOpen}
        onClose={() => setAssistOpen(false)}
        hint={t("categories.assistHint")}
        examples={[t("categories.assistEx1"), t("categories.assistEx2"), t("categories.assistEx3")]}
      />
      {merge && <MergeModal source={merge} onClose={() => setMerge(null)} />}
    </div>
  );
}

function Row({
  n,
  depth,
  canWrite,
  onEdit,
  onAdd,
  onMerge,
}: {
  n: TreeNode<Category>;
  depth: number;
  canWrite: boolean;
  onEdit: (c: Category) => void;
  onAdd: (parent: string) => void;
  onMerge: (c: Category) => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const [open, setOpen] = useState(true);
  const c = n.node;
  const has = n.children.length > 0;
  const remove = useApiMutation(() => api_.deleteCategory(c.id), {
    onSuccess: () => toast(t("common.done")),
  });
  return (
    <li>
      <div
        className={clsx(
          "group flex items-center gap-1 rounded-lg pr-2 hover:bg-slate-100 dark:hover:bg-slate-800",
        )}
        style={{ paddingLeft: depth * 18 }}
      >
        <button
          className="grid size-8 place-items-center text-slate-400"
          onClick={() => setOpen((o) => !o)}
          disabled={!has}
          aria-label={open ? "Sbalit" : "Rozbalit"}
        >
          {has ? (
            open ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )
          ) : (
            <span className="size-1 rounded-full bg-slate-300" />
          )}
        </button>
        <Link
          to={`/items?category_id=${c.id}`}
          className="flex min-w-0 flex-1 items-center gap-2 py-1.5 text-sm"
        >
          <span className="truncate font-medium">{c.name}</span>
          <span className="text-xs text-slate-400">{c.item_count}</span>
        </Link>
        {canWrite && (
          <div className="flex gap-0.5">
            <Button
              size="sm"
              variant="ghost"
              aria-label={t("categories.addChild")}
              title={t("categories.addChild")}
              onClick={() => onAdd(c.id)}
            >
              <Plus className="size-4" />
              <span className="hidden text-xs lg:inline">{t("categories.addChildShort")}</span>
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={t("common.edit")}
              title={t("common.edit")}
              onClick={() => onEdit(c)}
            >
              <Edit3 className="size-4" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={t("categories.merge")}
              title={t("categories.merge")}
              onClick={() => onMerge(c)}
            >
              <GitMerge className="size-4" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={t("common.delete")}
              title={t("common.delete")}
              onClick={async () => {
                try {
                  await remove.mutateAsync(undefined);
                } catch (e) {
                  toast(errorMessage(e), "error");
                }
              }}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        )}
      </div>
      {has && open && (
        <ul>
          {n.children.map((ch) => (
            <Row
              key={ch.node.id}
              n={ch}
              depth={depth + 1}
              canWrite={canWrite}
              onEdit={onEdit}
              onAdd={onAdd}
              onMerge={onMerge}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

function CategoryFormModal({
  edit,
  parent,
  onClose,
  onAssist,
}: {
  edit?: Category;
  parent?: string | null;
  /** Nabídka „popsat asistentovi“ (jen při vytváření). */
  onAssist?: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const [name, setName] = useState(edit?.name ?? "");
  const [parentId, setParentId] = useState<string | null>(edit ? edit.parent_id : (parent ?? null));
  const [description, setDescription] = useState(edit?.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const save = useApiMutation(
    () => {
      const body = {
        name: name.trim(),
        parent_id: parentId,
        description: description.trim() || null,
      };
      return edit
        ? api_.updateCategory(edit.id, { ...body, version: edit.version })
        : api_.createCategory(body);
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
  return (
    <Modal open onClose={onClose} title={edit ? t("categories.edit") : t("categories.add")}>
      <form onSubmit={submit} className="space-y-4">
        {!edit && onAssist && (
          <button
            type="button"
            onClick={onAssist}
            className="flex w-full items-center gap-2 rounded-lg bg-brand-50 px-3 py-2 text-left text-sm text-brand-700 hover:bg-brand-100 dark:bg-brand-700/20 dark:text-brand-100"
          >
            <Sparkles className="size-4 shrink-0" />
            <span>{t("categories.assistLink")}</span>
          </button>
        )}
        <Field label={t("categories.name")}>
          {(id) => (
            <Input
              id={id}
              autoFocus
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("categories.parent")}>
          {(id) => (
            <CategorySelect
              id={id}
              value={parentId}
              onChange={setParentId}
              exclude={edit?.id}
              emptyLabel={t("categories.root")}
            />
          )}
        </Field>
        <Field label={t("items.description")}>
          {(id) => (
            <Textarea
              id={id}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          )}
        </Field>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={save.isPending || !name.trim()}>
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function MergeModal({ source, onClose }: { source: Category; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [target, setTarget] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const merge = useApiMutation(() => api_.mergeCategory(source.id, target!), {
    onSuccess: () => {
      toast(t("common.done"));
      onClose();
    },
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={t("categories.mergeTitle", { name: source.name })}
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
              } catch (e) {
                setError(errorMessage(e));
              }
            }}
          >
            {t("categories.merge")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm">{t("categories.mergeHint", { count: source.item_count })}</p>
        <Field label={t("categories.mergeTarget")}>
          {(id) => (
            <CategorySelect
              id={id}
              value={target}
              onChange={setTarget}
              exclude={source.id}
              emptyLabel={t("categories.chooseTarget")}
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
