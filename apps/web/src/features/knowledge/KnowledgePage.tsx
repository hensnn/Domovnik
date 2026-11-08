import { Pencil, Plus, Power, Search, Trash2 } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api_, useApiMutation, useKnowledge, useSettings } from "../../api/hooks";
import type { Knowledge, KnowledgeTopic } from "../../api/types";
import {
  Badge,
  Button,
  Card,
  Chip,
  EmptyState,
  Field,
  IconButton,
  Input,
  Modal,
  Select,
  Spinner,
  Textarea,
  errorMessage,
  useToast,
} from "../../components/ui";
import { useAuth } from "../auth/AuthProvider";

const TOPICS: KnowledgeTopic[] = ["rules", "household", "naming", "other"];
const TITLE_MAX = 200;
const CONTENT_MAX = 2000;

type Dialog =
  { kind: "edit"; entry: Knowledge | null } | { kind: "delete"; entry: Knowledge } | null;

/**
 * Knihovna znalostí AI: co asistent ví o domácnosti (pravidla uspořádání, zvyky, pojmenování).
 * Zapnuté záznamy AI dodržuje a neptá se na ně znovu. Spravuje je admin; ostatní čtou.
 */
export default function KnowledgePage() {
  const { t } = useTranslation();
  const { isAdmin } = useAuth();
  const { data, isPending, isError, error } = useKnowledge();
  const settings = useSettings();
  const [topic, setTopic] = useState<KnowledgeTopic | "all">("all");
  const [filter, setFilter] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);

  const maxChars = Number(
    settings.data?.find((s) => s.key === "ai.knowledge_max_chars")?.value ?? 4000,
  );
  const enabledOn = settings.data?.find((s) => s.key === "ai.knowledge_enabled")?.value !== false;
  const used = useMemo(
    () =>
      (data ?? [])
        .filter((e) => e.enabled)
        .reduce((n, e) => n + e.title.length + e.content.length + 20, 0),
    [data],
  );
  const pending = (data ?? []).filter((e) => !e.enabled && e.source === "ai").length;

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return (data ?? []).filter(
      (e) =>
        (topic === "all" || e.topic === topic) &&
        (!needle || `${e.title} ${e.content}`.toLowerCase().includes(needle)),
    );
  }, [data, topic, filter]);

  return (
    <div className="mx-auto max-w-3xl space-y-3 p-3 md:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-xl font-bold">
          {t("knowledge.title")}
          <span className="ml-2 text-sm font-normal text-slate-500">{data?.length ?? 0}</span>
        </h1>
        {isAdmin && (
          <Button
            variant="primary"
            size="sm"
            onClick={() => setDialog({ kind: "edit", entry: null })}
          >
            <Plus className="size-4" /> {t("knowledge.add")}
          </Button>
        )}
      </div>
      <p className="text-sm text-slate-500">{t("knowledge.intro")}</p>

      {!enabledOn && (
        <p role="status" className="rounded-lg bg-amber-50 p-3 text-sm dark:bg-amber-950/40">
          {t("knowledge.disabled")}
        </p>
      )}
      {isAdmin && pending > 0 && (
        <p role="status" className="rounded-lg bg-sky-50 p-3 text-sm dark:bg-sky-950/40">
          {t("knowledge.pendingNotice", { count: pending })}
        </p>
      )}

      <Card className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-40 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={t("knowledge.filter")}
              aria-label={t("knowledge.filter")}
              className="pl-9"
            />
          </div>
        </div>
        <div className="flex flex-wrap gap-1" role="group" aria-label={t("knowledge.topicLabel")}>
          <Chip active={topic === "all"} onClick={() => setTopic("all")}>
            {t("common.all")}
          </Chip>
          {TOPICS.map((tp) => (
            <Chip key={tp} active={topic === tp} onClick={() => setTopic(tp)}>
              {t(`knowledge.topic.${tp}`)}
            </Chip>
          ))}
        </div>
        {isAdmin && (
          <p
            className={used > maxChars ? "text-xs text-amber-600" : "text-xs text-slate-500"}
            aria-live="polite"
          >
            {t("knowledge.usage", { used, max: maxChars })}
            {used > maxChars && ` ${t("knowledge.usageOver")}`}
          </p>
        )}

        {isPending ? (
          <Spinner />
        ) : isError ? (
          <p role="alert" className="text-red-600">
            {errorMessage(error)}
          </p>
        ) : shown.length === 0 ? (
          <EmptyState
            title={data?.length ? t("knowledge.noMatch") : t("knowledge.empty")}
            hint={data?.length ? undefined : t("knowledge.emptyHint")}
          />
        ) : (
          <ul className="space-y-2">
            {shown.map((e) => (
              <li
                key={e.id}
                className={
                  "rounded-xl border border-slate-200 p-3 dark:border-slate-800 " +
                  (e.enabled ? "" : "opacity-70")
                }
              >
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="mr-auto min-w-0 font-medium">{e.title}</h2>
                  <Badge>{t(`knowledge.topic.${e.topic}`)}</Badge>
                  {e.source === "ai" && <Badge tone="blue">{t("knowledge.byAi")}</Badge>}
                  {!e.enabled && (
                    <Badge tone="amber">
                      {e.source === "ai" ? t("knowledge.waiting") : t("knowledge.off")}
                    </Badge>
                  )}
                </div>
                <p className="mt-1 whitespace-pre-wrap break-words text-sm text-slate-700 dark:text-slate-300">
                  {e.content}
                </p>
                {isAdmin && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    <ToggleButton entry={e} />
                    <IconButton
                      label={t("knowledge.edit", { title: e.title })}
                      onClick={() => setDialog({ kind: "edit", entry: e })}
                    >
                      <Pencil className="size-4" />
                    </IconButton>
                    <IconButton
                      label={t("knowledge.delete", { title: e.title })}
                      onClick={() => setDialog({ kind: "delete", entry: e })}
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
        <EditDialog entry={dialog.entry} onClose={() => setDialog(null)} />
      )}
      {dialog?.kind === "delete" && (
        <DeleteDialog entry={dialog.entry} onClose={() => setDialog(null)} />
      )}
    </div>
  );
}

/** Zapnout / vypnout záznam (po schválení návrhu od AI se záznam zapne tímto tlačítkem). */
function ToggleButton({ entry }: { entry: Knowledge }) {
  const { t } = useTranslation();
  const toast = useToast();
  const toggle = useApiMutation(() =>
    api_.updateKnowledge(entry.id, { enabled: !entry.enabled }, entry.version),
  );
  return (
    <Button
      size="sm"
      disabled={toggle.isPending}
      aria-pressed={entry.enabled}
      onClick={async () => {
        try {
          await toggle.mutateAsync(undefined);
        } catch (e) {
          toast(errorMessage(e), "error");
        }
      }}
    >
      <Power className="size-4" />
      {entry.enabled
        ? t("knowledge.turnOff")
        : entry.source === "ai"
          ? t("knowledge.approve")
          : t("knowledge.turnOn")}
    </Button>
  );
}

function EditDialog({ entry, onClose }: { entry: Knowledge | null; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [title, setTitle] = useState(entry?.title ?? "");
  const [content, setContent] = useState(entry?.content ?? "");
  const [topic, setTopic] = useState<KnowledgeTopic>(entry?.topic ?? "rules");
  const [enabled, setEnabled] = useState(entry?.enabled ?? true);
  const [error, setError] = useState<string | null>(null);

  const save = useApiMutation(
    () => {
      const body = { title: title.trim(), content: content.trim(), topic, enabled };
      return entry
        ? api_.updateKnowledge(entry.id, body, entry.version)
        : api_.createKnowledge(body);
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
  const examples = [t("knowledge.ex1"), t("knowledge.ex2"), t("knowledge.ex3")];

  return (
    <Modal
      open
      onClose={onClose}
      title={entry ? t("knowledge.editTitle") : t("knowledge.add")}
      wide
    >
      <form onSubmit={submit} className="space-y-4">
        {!entry && (
          <div className="space-y-1">
            <p className="text-xs text-slate-500">{t("knowledge.examples")}</p>
            <div className="flex flex-wrap gap-1">
              {examples.map((ex) => {
                const [exTitle, ...rest] = ex.split(" | ");
                return (
                  <Chip
                    key={ex}
                    active={false}
                    onClick={() => {
                      setTitle(exTitle);
                      setContent(rest.join(" | "));
                    }}
                  >
                    {exTitle}
                  </Chip>
                );
              })}
            </div>
          </div>
        )}
        <Field label={t("knowledge.fieldTitle")}>
          {(id) => (
            <Input
              id={id}
              autoFocus
              required
              maxLength={TITLE_MAX}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("knowledge.titlePlaceholder")}
            />
          )}
        </Field>
        <Field label={t("knowledge.fieldTopic")}>
          {(id) => (
            <Select
              id={id}
              value={topic}
              onChange={(e) => setTopic(e.target.value as KnowledgeTopic)}
            >
              {TOPICS.map((tp) => (
                <option key={tp} value={tp}>
                  {t(`knowledge.topic.${tp}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field
          label={t("knowledge.fieldContent")}
          hint={t("knowledge.contentHint", { count: content.length, max: CONTENT_MAX })}
        >
          {(id) => (
            <Textarea
              id={id}
              required
              rows={5}
              maxLength={CONTENT_MAX}
              lang="cs"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder={t("knowledge.contentPlaceholder")}
            />
          )}
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="size-4"
          />
          {t("knowledge.enabledLabel")}
        </label>
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
            disabled={!title.trim() || !content.trim() || save.isPending}
          >
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function DeleteDialog({ entry, onClose }: { entry: Knowledge; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const remove = useApiMutation(() => api_.deleteKnowledge(entry.id), {
    onSuccess: () => {
      toast(t("common.done"));
      onClose();
    },
  });
  return (
    <Modal
      open
      onClose={onClose}
      title={t("knowledge.deleteTitle", { title: entry.title })}
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
              } catch (e) {
                setError(errorMessage(e));
              }
            }}
          >
            {t("common.delete")}
          </Button>
        </>
      }
    >
      <p className="text-sm">{t("knowledge.deleteHint")}</p>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {error}
        </p>
      )}
    </Modal>
  );
}
