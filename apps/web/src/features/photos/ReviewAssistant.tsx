import { Loader2, SendHorizontal, Sparkles, Undo2, X } from "lucide-react";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api_ } from "../../api/hooks";
import type { RefineDraftItem, RefineEdit } from "../../api/types";
import { Button, IconButton } from "../../components/ui";
import type { UndoEntry } from "../../lib/photos";
import { assistantErrorText } from "../assistant/AssistantPage";

interface Msg {
  id: number;
  role: "user" | "assistant";
  text: string;
  /** čísla položek, které asistent změnil */
  changed?: number[];
  undo?: UndoEntry[];
  undone?: boolean;
  error?: boolean;
}

let counter = 0;

/**
 * Asistent při kontrole nálezů z fotky: uživatel mu říká, co upravit („č. 2 je šroubovák“,
 * „všechno do Police 2“, „sluč duplicity“), asistent vrací návrhy úprav konceptu a ty se
 * hned projeví v seznamu. Nic se neukládá – věci se zapíšou až závěrečným potvrzením
 * a každou úpravu asistenta jde vrátit.
 */
export default function ReviewAssistant({
  analysisId,
  getDraft,
  apply,
  undo,
  onClose,
}: {
  analysisId: string;
  getDraft: () => RefineDraftItem[];
  apply: (edits: RefineEdit[]) => { undo: UndoEntry[]; touched: string[]; indexes: number[] };
  undo: (entries: UndoEntry[]) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);
  const touch = typeof window !== "undefined" && !!window.matchMedia?.("(pointer: coarse)").matches;

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [msgs, busy]);

  const lastUndoable = [...msgs].reverse().find((m) => m.undo?.length && !m.undone);

  async function send(raw: string) {
    const msg = raw.trim();
    if (!msg || busy) return;
    setText("");
    setBusy(true);
    const history = msgs
      .filter((m) => !m.error)
      .slice(-10)
      .map((m) => ({ role: m.role, text: m.text }));
    setMsgs((l) => [...l, { id: ++counter, role: "user", text: msg }]);
    try {
      const res = await api_.refineAnalysis(analysisId, { text: msg, draft: getDraft(), history });
      const applied = res.edits.length ? apply(res.edits) : null;
      setMsgs((l) => [
        ...l,
        {
          id: ++counter,
          role: "assistant",
          text: res.reply,
          changed: applied?.indexes,
          undo: applied?.undo,
        },
      ]);
    } catch (err) {
      setMsgs((l) => [
        ...l,
        { id: ++counter, role: "assistant", text: assistantErrorText(err, t), error: true },
      ]);
    } finally {
      setBusy(false);
    }
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (touch) return; // na telefonu je Enter nový řádek, odesílá tlačítko
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(text);
    }
  };

  const quick = [t("photos.assistant.q1"), t("photos.assistant.q2"), t("photos.assistant.q3")];

  return (
    <section
      aria-label={t("photos.assistant.title")}
      className="mb-2 space-y-2 rounded-xl border border-brand-200 bg-brand-50/60 p-2 dark:border-brand-700/40 dark:bg-brand-700/10"
    >
      <div className="flex items-center gap-2">
        <Sparkles className="size-4 text-brand-600" aria-hidden />
        <h3 className="mr-auto text-sm font-semibold">{t("photos.assistant.title")}</h3>
        <IconButton label={t("photos.assistant.close")} onClick={onClose}>
          <X className="size-4" />
        </IconButton>
      </div>

      {msgs.length === 0 && (
        <div className="space-y-1">
          <p className="text-xs text-slate-600 dark:text-slate-300">
            {t("photos.assistant.intro")}
          </p>
          <div className="flex flex-wrap gap-1">
            {quick.map((q) => (
              <button
                key={q}
                type="button"
                disabled={busy}
                onClick={() => void send(q)}
                className="rounded-full border border-slate-300 bg-white px-2.5 py-1 text-xs hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {msgs.length > 0 && (
        <div
          role="log"
          aria-live="polite"
          aria-label={t("photos.assistant.log")}
          className="max-h-[26dvh] space-y-1.5 overflow-y-auto pr-1 text-sm"
        >
          {msgs.map((m) => (
            <div key={m.id} className={m.role === "user" ? "text-right" : "text-left"}>
              <div
                className={
                  "inline-block max-w-[92%] whitespace-pre-wrap break-words rounded-2xl px-3 py-1.5 text-left " +
                  (m.role === "user"
                    ? "bg-brand-600 text-white"
                    : m.error
                      ? "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300"
                      : "bg-white text-slate-900 dark:bg-slate-800 dark:text-slate-100")
                }
              >
                {m.text}
              </div>
              {m.role === "assistant" && m.changed && m.changed.length > 0 && (
                <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span>
                    {t("photos.assistant.changed", {
                      items: [...m.changed].sort((a, b) => a - b).join(", "),
                    })}
                  </span>
                  {m.undone ? (
                    <span>{t("photos.assistant.undone")}</span>
                  ) : (
                    m === lastUndoable && (
                      <button
                        type="button"
                        onClick={() => {
                          undo(m.undo ?? []);
                          setMsgs((l) =>
                            l.map((x) => (x.id === m.id ? { ...x, undone: true } : x)),
                          );
                        }}
                        className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium text-brand-700 hover:bg-white dark:text-brand-100 dark:hover:bg-slate-800"
                      >
                        <Undo2 className="size-3" /> {t("photos.assistant.undo")}
                      </button>
                    )
                  )}
                </div>
              )}
            </div>
          ))}
          {busy && (
            <p role="status" className="flex items-center gap-2 text-xs text-slate-500">
              <Loader2 className="size-3 animate-spin" aria-hidden /> {t("assistant.thinking")}
            </p>
          )}
          <div ref={endRef} />
        </div>
      )}

      <div className="flex items-end gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          rows={touch ? 2 : 1}
          maxLength={2000}
          lang="cs"
          autoCapitalize="sentences"
          enterKeyHint={touch ? "enter" : "send"}
          disabled={busy}
          placeholder={t("photos.assistant.placeholder")}
          aria-label={t("photos.assistant.placeholder")}
          className="min-h-10 flex-1 resize-none rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30 dark:border-slate-700 dark:bg-slate-900"
        />
        <Button
          variant="primary"
          className="!size-10 shrink-0 !p-0"
          aria-label={t("assistant.send")}
          title={t("assistant.send")}
          disabled={busy || !text.trim()}
          onClick={() => void send(text)}
        >
          {busy ? (
            <Loader2 className="size-5 animate-spin" />
          ) : (
            <SendHorizontal className="size-5" />
          )}
        </Button>
      </div>
    </section>
  );
}
