import type { TFunction } from "i18next";
import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  History,
  Loader2,
  MessageSquarePlus,
  Mic,
  MicOff,
  SendHorizontal,
  Trash2,
  Volume2,
} from "lucide-react";
import {
  type KeyboardEvent,
  type PointerEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { ApiError } from "../../api/client";
import { api_, useAiStatus, useApiMutation, useConversations, useSettings } from "../../api/hooks";
import { streamChat } from "../../api/sse";
import type { ChangeSet, ChatEvent, Conversation } from "../../api/types";
import { LocationSelect } from "../../components/Pickers";
import {
  Button,
  Drawer,
  IconButton,
  Modal,
  Spinner,
  errorMessage,
  useToast,
} from "../../components/ui";
import { formatDateTime } from "../../lib/format";
import { useCurrentLocation } from "../../lib/currentLocation";
import { useAuth } from "../auth/AuthProvider";
import ChangeSetCard from "./ChangeSetCard";
import {
  shouldSpeak,
  speak,
  stopSpeaking,
  ttsSupported,
  voicePrefs,
  useSpeechRecognition,
} from "./voice";

interface ChatItem {
  id: string;
  role: "user" | "assistant";
  text: string;
  voice?: boolean;
  tools?: string[];
  changeSets?: ChangeSet[];
  error?: string;
  pending?: boolean;
}

let counter = 0;
const nextId = () => `m${Date.now()}-${counter++}`;

/** Text průběhu podle názvu nástroje, který asistent právě volá. */
export function toolLabelKey(name: string): string {
  const known = [
    "search_items",
    "get_item",
    "get_location_contents",
    "list_locations",
    "list_categories",
    "find_duplicates",
    "get_item_history",
    "get_stats",
    "propose_changes",
    "confirm_pending_changes",
  ];
  return known.includes(name) ? `assistant.tool.${name}` : "assistant.tool.default";
}

/** Převede chybu API na srozumitelnou českou hlášku (503 = není nakonfigurováno, 429 = limit). */
export function assistantErrorText(err: unknown, t: TFunction): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return `${t("assistant.errors.rateLimit")} ${err.message}`.trim();
    if (err.status === 503) return `${t("assistant.errors.unavailable")} ${err.message}`.trim();
    if (err.status === 403) return t("assistant.errors.forbidden");
  }
  return errorMessage(err);
}

export default function AssistantPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const { can } = useAuth();
  const canWrite = can("items:write");
  const status = useAiStatus();
  const settings = useSettings();
  const conversations = useConversations();
  const prefs = voicePrefs(settings.data);

  const [convId, setConvId] = useState<string | null>(null);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [toDelete, setToDelete] = useState<Conversation | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [currentLoc, setCurrentLoc] = useCurrentLocation();
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const openToken = useRef(0);
  const [loadingHistory, setLoadingHistory] = useState(false);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [items, progress]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      stopSpeaking();
    },
    [],
  );

  const patchLast = useCallback((fn: (m: ChatItem) => ChatItem) => {
    setItems((list) => {
      if (!list.length) return list;
      const copy = list.slice();
      copy[copy.length - 1] = fn(copy[copy.length - 1]);
      return copy;
    });
  }, []);

  const send = useCallback(
    async (raw: string, viaVoice: boolean) => {
      const msg = raw.trim();
      if (!msg || busy) return;
      setText("");
      setBusy(true);
      setProgress(null);
      setItems((l) => [
        ...l,
        { id: nextId(), role: "user", text: msg, voice: viaVoice },
        { id: nextId(), role: "assistant", text: "", pending: true, tools: [], changeSets: [] },
      ]);
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      let newConv = convId;
      let reply = "";
      let sawChange = false;
      const onEvent = (e: ChatEvent) => {
        switch (e.type) {
          case "conversation":
            newConv = e.conversation_id;
            setConvId(e.conversation_id);
            break;
          case "tool_call":
            setProgress(e.name);
            patchLast((m) => ({ ...m, tools: [...(m.tools ?? []), e.name] }));
            break;
          case "change_set":
            sawChange = true;
            patchLast((m) => ({
              ...m,
              changeSets: [
                ...(m.changeSets ?? []).filter((c) => c.id !== e.change_set.id),
                e.change_set,
              ],
            }));
            break;
          case "message":
            reply = e.text;
            patchLast((m) => ({ ...m, text: e.text }));
            break;
          case "done":
            newConv = e.conversation_id || newConv;
            if (e.reply && !reply) {
              reply = e.reply;
              patchLast((m) => ({ ...m, text: e.reply }));
            }
            if (e.error) patchLast((m) => ({ ...m, error: e.error ?? undefined }));
            break;
          case "error":
            patchLast((m) => ({ ...m, error: e.message }));
            break;
        }
      };
      try {
        await streamChat(
          {
            text: msg,
            conversation_id: convId,
            context_location_id: currentLoc,
            channel: viaVoice ? "voice" : "text",
          },
          onEvent,
          ctrl.signal,
        );
      } catch (err) {
        if (!(err instanceof DOMException && err.name === "AbortError")) {
          patchLast((m) => ({ ...m, error: assistantErrorText(err, t) }));
        }
      } finally {
        patchLast((m) => ({ ...m, pending: false }));
        setBusy(false);
        setProgress(null);
        abortRef.current = null;
        if (newConv) setConvId(newConv);
        void qc.invalidateQueries({ queryKey: ["ai", "conversations"] });
        void qc.invalidateQueries({ queryKey: ["ai", "status"] });
        if (sawChange) {
          for (const k of ["items", "item", "locations", "categories", "tags", "stats", "search"])
            void qc.invalidateQueries({ queryKey: [k] });
        }
        if (reply && shouldSpeak(prefs, viaVoice)) {
          setSpeaking(speak(reply, prefs.ttsSpeed));
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      busy,
      convId,
      currentLoc,
      patchLast,
      qc,
      t,
      prefs.ttsEngine,
      prefs.speakReplies,
      prefs.ttsSpeed,
    ],
  );

  const mic = useSpeechRecognition(
    (finalText) => void send(finalText, true),
    (code) => {
      if (code === "not-allowed" || code === "service-not-allowed")
        toast(t("assistant.voice.denied"), "error");
      else if (code === "no-speech") toast(t("assistant.voice.noSpeech"), "error");
      else if (code !== "aborted") toast(t("assistant.voice.error", { code }), "error");
    },
  );

  const newConversation = () => {
    abortRef.current?.abort();
    stopSpeaking();
    openToken.current++;
    setLoadingHistory(false);
    setConvId(null);
    setItems([]);
    setHistoryOpen(false);
  };
  const openConversation = async (id: string) => {
    abortRef.current?.abort();
    stopSpeaking();
    const token = ++openToken.current;
    setItems([]);
    setConvId(id);
    setHistoryOpen(false);
    setLoadingHistory(true);
    try {
      const msgs = await api_.conversationMessages(id);
      if (token !== openToken.current) return;
      setItems(msgs.map((m) => ({ id: `s${m.id}`, role: m.role, text: m.content })));
    } catch (e) {
      if (token === openToken.current) toast(errorMessage(e), "error");
    } finally {
      if (token === openToken.current) setLoadingHistory(false);
    }
  };

  const remove = useApiMutation((id: string) => api_.deleteConversation(id), {
    invalidate: false,
    onSuccess: (_r, id) => {
      void qc.invalidateQueries({ queryKey: ["ai", "conversations"] });
      if (id === convId) newConversation();
      setToDelete(null);
    },
  });

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(text, false);
    }
  };

  // --- mikrofon: podrž = mluv dokud držíš, klepnutí = zapne / vypne poslech ---
  const holdStart = useRef(0);
  const micEnabled = prefs.sttEngine === "browser" && mic.supported;
  const onMicDown = (e: PointerEvent<HTMLButtonElement>) => {
    if (!micEnabled || busy) return;
    e.preventDefault();
    if (mic.listening) {
      mic.stop();
      holdStart.current = 0;
    } else {
      holdStart.current = Date.now();
      mic.start();
    }
  };
  const onMicUp = () => {
    if (holdStart.current && Date.now() - holdStart.current > 600) mic.stop();
    holdStart.current = 0;
  };
  const onMicClick = (e: React.MouseEvent) => {
    // klávesnice (detail 0): přepíná; myš/dotyk řeší pointer události
    if (e.detail !== 0 || !micEnabled || busy) return;
    if (mic.listening) mic.stop();
    else mic.start();
  };

  const micHint = !mic.supported
    ? t("assistant.voice.unsupported")
    : prefs.sttEngine === "off"
      ? t("assistant.voice.off")
      : prefs.sttEngine !== "browser"
        ? t("assistant.voice.engineUnavailable", { engine: prefs.sttEngine })
        : mic.listening
          ? t("assistant.voice.stop")
          : t("assistant.voice.start");

  const st = status.data;
  const list = (
    <ConversationList
      items={conversations.data}
      loading={conversations.isPending}
      activeId={convId}
      onOpen={(id) => void openConversation(id)}
      onNew={newConversation}
      onDelete={setToDelete}
    />
  );

  return (
    <div className="mx-auto flex h-full max-w-6xl gap-3 p-3 md:p-5">
      <aside className="hidden w-64 shrink-0 flex-col md:flex" aria-label={t("assistant.history")}>
        {list}
      </aside>

      <section className="flex min-w-0 flex-1 flex-col" aria-label={t("nav.assistant")}>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h1 className="mr-auto text-xl font-bold">{t("nav.assistant")}</h1>
          {st && (
            <span className="text-xs text-slate-500">
              {t("assistant.quota", { used: st.requests_today, limit: st.requests_per_day_limit })}
            </span>
          )}
          <IconButton
            label={t("assistant.history")}
            className="md:hidden"
            onClick={() => setHistoryOpen(true)}
          >
            <History className="size-5" />
          </IconButton>
          <Button size="sm" className="md:hidden" onClick={newConversation}>
            <MessageSquarePlus className="size-4" /> {t("assistant.new")}
          </Button>
        </div>

        {st && !st.enabled && (
          <p role="status" className="mb-2 rounded-lg bg-amber-50 p-3 text-sm dark:bg-amber-950/40">
            {t("assistant.disabled")}
          </p>
        )}
        {st && st.enabled && !st.configured && (
          <p role="status" className="mb-2 rounded-lg bg-amber-50 p-3 text-sm dark:bg-amber-950/40">
            {t("assistant.notConfigured")}{" "}
            <Link
              to="/settings?tab=ai"
              className="font-medium text-brand-700 underline dark:text-brand-100"
            >
              {t("assistant.openSettings")}
            </Link>
          </p>
        )}

        <div
          className="min-h-0 flex-1 space-y-3 overflow-y-auto rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900"
          role="log"
          aria-live="polite"
          aria-label={t("assistant.log")}
        >
          {loadingHistory && <Spinner label={t("assistant.loading")} />}
          {!items.length && !loadingHistory && (
            <div className="space-y-2 p-4 text-center text-sm text-slate-500">
              <p className="font-medium text-slate-700 dark:text-slate-200">
                {t("assistant.welcome")}
              </p>
              <p>{t("assistant.welcomeHint")}</p>
              <div className="flex flex-wrap justify-center gap-2 pt-1">
                {(["ex1", "ex2", "ex3"] as const).map((k) => (
                  <button
                    key={k}
                    onClick={() => setText(t(`assistant.${k}`))}
                    className="rounded-full border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
                  >
                    {t(`assistant.${k}`)}
                  </button>
                ))}
              </div>
            </div>
          )}
          {items.map((m) => (
            <Message
              key={m.id}
              item={m}
              progress={m.pending ? progress : null}
              canWrite={canWrite}
            />
          ))}
          <div ref={endRef} />
        </div>

        <div className="mt-2 space-y-2">
          <div className="flex items-center gap-2 text-sm">
            <label htmlFor="here" className="shrink-0 text-slate-500">
              {t("assistant.hereLabel")}
            </label>
            <div className="min-w-0 flex-1">
              <LocationSelect
                id="here"
                value={currentLoc}
                onChange={setCurrentLoc}
                emptyLabel={t("assistant.hereNone")}
              />
            </div>
          </div>
          {mic.listening && (
            <p role="status" className="flex items-center gap-2 text-sm text-red-600">
              <span className="size-2 animate-pulse rounded-full bg-red-600" aria-hidden />
              {mic.interim || t("assistant.voice.listening")}
            </p>
          )}
          <div className="flex items-end gap-2">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={onKey}
              rows={2}
              maxLength={4000}
              placeholder={t("assistant.placeholder")}
              aria-label={t("assistant.placeholder")}
              disabled={busy}
              className="min-h-11 flex-1 resize-none rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30 dark:border-slate-700 dark:bg-slate-900"
            />
            <button
              type="button"
              aria-label={micHint}
              title={micHint}
              aria-pressed={mic.listening}
              disabled={!micEnabled || busy}
              onPointerDown={onMicDown}
              onPointerUp={onMicUp}
              onClick={onMicClick}
              className={clsx(
                "flex size-11 shrink-0 touch-none items-center justify-center rounded-lg border",
                mic.listening
                  ? "border-red-500 bg-red-600 text-white"
                  : "border-slate-300 bg-white hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800",
                "disabled:cursor-not-allowed disabled:opacity-50",
              )}
            >
              {micEnabled ? <Mic className="size-5" /> : <MicOff className="size-5" />}
            </button>
            {speaking && ttsSupported() && (
              <IconButton
                label={t("assistant.voice.stopSpeaking")}
                onClick={() => {
                  stopSpeaking();
                  setSpeaking(false);
                }}
                className="!size-11 border border-slate-300 dark:border-slate-700"
              >
                <Volume2 className="size-5" />
              </IconButton>
            )}
            <Button
              variant="primary"
              className="!size-11 shrink-0 !p-0"
              aria-label={t("assistant.send")}
              title={t("assistant.send")}
              disabled={busy || !text.trim()}
              onClick={() => void send(text, false)}
            >
              {busy ? (
                <Loader2 className="size-5 animate-spin" />
              ) : (
                <SendHorizontal className="size-5" />
              )}
            </Button>
          </div>
          {!micEnabled && <p className="text-xs text-slate-500">{micHint}</p>}
        </div>
      </section>

      <Drawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        title={<span className="font-semibold">{t("assistant.history")}</span>}
      >
        <div className="p-3">{list}</div>
      </Drawer>

      <Modal
        open={!!toDelete}
        onClose={() => setToDelete(null)}
        title={t("assistant.deleteTitle")}
        footer={
          <>
            <Button onClick={() => setToDelete(null)}>{t("common.cancel")}</Button>
            <Button
              variant="danger"
              disabled={remove.isPending}
              onClick={() => toDelete && remove.mutate(toDelete.id)}
            >
              {t("common.delete")}
            </Button>
          </>
        }
      >
        <p className="text-sm">{t("assistant.deleteHint", { title: toDelete?.title ?? "" })}</p>
        {remove.isError && (
          <p role="alert" className="mt-2 text-sm text-red-600">
            {errorMessage(remove.error)}
          </p>
        )}
      </Modal>
    </div>
  );
}

function Message({
  item,
  progress,
  canWrite,
}: {
  item: ChatItem;
  progress: string | null;
  canWrite: boolean;
}) {
  const { t } = useTranslation();
  const mine = item.role === "user";
  return (
    <div className={clsx("flex", mine ? "justify-end" : "justify-start")}>
      <div className={clsx("max-w-[92%] space-y-2 md:max-w-[80%]", mine && "text-right")}>
        {(item.text || (item.pending && !item.changeSets?.length)) && (
          <div
            className={clsx(
              "inline-block whitespace-pre-wrap break-words rounded-2xl px-3 py-2 text-left text-sm",
              mine
                ? "bg-brand-600 text-white"
                : "bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-100",
            )}
          >
            {item.text ||
              (item.pending && (
                <span className="flex items-center gap-2 text-slate-500" role="status">
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  {progress ? t(toolLabelKey(progress)) : t("assistant.thinking")}
                </span>
              ))}
          </div>
        )}
        {item.changeSets?.map((cs) => (
          <div key={cs.id} className="text-left">
            <ChangeSetCard changeSet={cs} canWrite={canWrite} />
          </div>
        ))}
        {item.error && (
          <p
            role="alert"
            className="inline-block rounded-lg bg-red-50 px-3 py-2 text-left text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300"
          >
            {item.error}
          </p>
        )}
        {mine && item.voice && (
          <p className="flex items-center justify-end gap-1 text-xs text-slate-400">
            <Mic className="size-3" aria-hidden /> {t("assistant.voice.sent")}
          </p>
        )}
      </div>
    </div>
  );
}

function ConversationList({
  items,
  loading,
  activeId,
  onOpen,
  onNew,
  onDelete,
}: {
  items: Conversation[] | undefined;
  loading: boolean;
  activeId: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
  onDelete: (c: Conversation) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <Button onClick={onNew}>
        <MessageSquarePlus className="size-4" /> {t("assistant.new")}
      </Button>
      {loading ? (
        <Spinner />
      ) : !items?.length ? (
        <p className="p-2 text-sm text-slate-500">{t("assistant.noHistory")}</p>
      ) : (
        <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {items.map((c) => (
            <li key={c.id} className="group flex items-center gap-1">
              <button
                onClick={() => onOpen(c.id)}
                aria-current={c.id === activeId}
                className={clsx(
                  "min-w-0 flex-1 rounded-lg px-3 py-2 text-left text-sm",
                  c.id === activeId
                    ? "bg-brand-50 text-brand-700 dark:bg-brand-700/20 dark:text-brand-100"
                    : "hover:bg-slate-100 dark:hover:bg-slate-800",
                )}
              >
                <span className="block truncate font-medium">
                  {c.title || t("assistant.untitled")}
                </span>
                <span className="block text-xs text-slate-500">{formatDateTime(c.created_at)}</span>
              </button>
              <IconButton
                label={t("assistant.deleteConversation", { title: c.title ?? "" })}
                onClick={() => onDelete(c)}
              >
                <Trash2 className="size-4" />
              </IconButton>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
