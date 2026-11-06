// SSE v těle odpovědi na POST (EventSource neumí POST) – čtení přes fetch + ReadableStream.

import { errorFromResponse, getCsrfToken, safeJson } from "./client";
import type { ChatEvent } from "./types";

export interface SseMessage {
  event: string;
  data: string;
}

/** Inkrementální parser SSE: vkládej kusy textu, vrací dokončené zprávy. */
export class SseParser {
  private buffer = "";

  push(chunk: string): SseMessage[] {
    this.buffer += chunk;
    const out: SseMessage[] = [];
    // zprávy jsou odděleny prázdným řádkem (\n\n, \r\n\r\n nebo \r\r)
    for (;;) {
      const m = /\r\n\r\n|\n\n|\r\r/.exec(this.buffer);
      if (!m) break;
      const raw = this.buffer.slice(0, m.index);
      this.buffer = this.buffer.slice(m.index + m[0].length);
      const msg = parseBlock(raw);
      if (msg) out.push(msg);
    }
    return out;
  }

  /** Na konci streamu zpracuje případný nedokončený blok. */
  flush(): SseMessage[] {
    const rest = this.buffer.trim();
    this.buffer = "";
    if (!rest) return [];
    const msg = parseBlock(rest);
    return msg ? [msg] : [];
  }
}

function parseBlock(raw: string): SseMessage | null {
  let event = "message";
  const data: string[] = [];
  for (const line of raw.split(/\r\n|\n|\r/)) {
    if (!line || line.startsWith(":")) continue;
    const idx = line.indexOf(":");
    const field = idx === -1 ? line : line.slice(0, idx);
    let value = idx === -1 ? "" : line.slice(idx + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (!data.length) return null;
  return { event, data: data.join("\n") };
}

/** Převede zprávu SSE na typovanou událost chatu (neznámé události ignoruje). */
export function toChatEvent(msg: SseMessage): ChatEvent | null {
  const d = safeJson(msg.data);
  if (!d || typeof d !== "object") return null;
  const type = msg.event;
  switch (type) {
    case "conversation":
    case "tool_call":
    case "change_set":
    case "message":
    case "done":
    case "error":
      return { ...(d as object), type } as ChatEvent;
    default:
      return null;
  }
}

export interface ChatRequest {
  text: string;
  conversation_id?: string | null;
  context_location_id?: string | null;
  channel: "text" | "voice";
}

/** Pošle zprávu asistentovi a průběžně předává události. Vyhodí ApiError při HTTP chybě. */
export async function streamChat(
  body: ChatRequest,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    "Content-Type": "application/json",
  };
  const csrf = getCsrfToken();
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const res = await fetch("/api/v1/ai/chat", {
    method: "POST",
    headers,
    body: JSON.stringify({
      text: body.text,
      conversation_id: body.conversation_id || undefined,
      context_location_id: body.context_location_id || undefined,
      channel: body.channel,
    }),
    credentials: "same-origin",
    signal,
  });
  if (!res.ok) {
    const text = await res.text();
    throw errorFromResponse(res.status, text ? safeJson(text) : null, "/ai/chat");
  }
  if (!res.body) throw new Error("Server nevrátil proud odpovědi.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  const emit = (msgs: SseMessage[]) => {
    for (const m of msgs) {
      const e = toChatEvent(m);
      if (e) onEvent(e);
    }
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    emit(parser.push(decoder.decode(value, { stream: true })));
  }
  emit(parser.push(decoder.decode()));
  emit(parser.flush());
}
