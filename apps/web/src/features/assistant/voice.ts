// Hlas v prohlížeči (Web Speech API): rozpoznávání řeči a čtení odpovědí. Funguje jen na HTTPS / localhost.

import { useCallback, useEffect, useRef, useState } from "react";

import type { SettingDef } from "../../api/types";

interface RecognitionResultItem {
  transcript: string;
}
interface RecognitionResult {
  isFinal: boolean;
  0: RecognitionResultItem;
  length: number;
}
interface RecognitionEvent {
  resultIndex: number;
  results: ArrayLike<RecognitionResult>;
}
export interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: RecognitionEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => SpeechRecognitionLike;

export function getRecognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const ttsSupported = () => typeof window !== "undefined" && "speechSynthesis" in window;

/** Nastavení hlasu z uživatelských/globálních nastavení (`voice.*`). */
export interface VoicePrefs {
  sttEngine: string;
  ttsEngine: string;
  ttsSpeed: number;
  speakReplies: "never" | "after_voice" | "always";
}

export function voicePrefs(settings: SettingDef[] | undefined): VoicePrefs {
  const val = (key: string, fallback: unknown) => {
    const s = settings?.find((x) => x.key === key);
    return s ? s.value : fallback;
  };
  const speed = Number(val("voice.tts_speed", 1));
  const mode = String(val("voice.speak_replies", "after_voice"));
  return {
    sttEngine: String(val("voice.stt_engine", "browser")),
    ttsEngine: String(val("voice.tts_engine", "browser")),
    ttsSpeed: Number.isFinite(speed) && speed > 0 ? speed : 1,
    speakReplies: mode === "never" || mode === "always" ? mode : "after_voice",
  };
}

/** Má se odpověď přečíst nahlas? */
export function shouldSpeak(prefs: VoicePrefs, viaVoice: boolean): boolean {
  if (prefs.ttsEngine !== "browser") return false;
  if (prefs.speakReplies === "always") return true;
  return prefs.speakReplies === "after_voice" && viaVoice;
}

/** Zbaví odpověď markdownu, aby se při čtení nevyslovovaly hvězdičky a mřížky. */
export function plainForSpeech(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/[*_`#>]+/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

export function speak(text: string, speed: number): boolean {
  if (!ttsSupported()) return false;
  const clean = plainForSpeech(text);
  if (!clean) return false;
  const synth = window.speechSynthesis;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(clean);
  u.lang = "cs-CZ";
  u.rate = speed;
  const voice = synth.getVoices().find((v) => v.lang.toLowerCase().startsWith("cs"));
  if (voice) u.voice = voice;
  synth.speak(u);
  return true;
}

export function stopSpeaking() {
  if (ttsSupported()) window.speechSynthesis.cancel();
}

/** Rozpoznávání řeči: `start()` začne poslouchat, finální přepis předá do `onFinal`. */
export function useSpeechRecognition(
  onFinal: (text: string) => void,
  onError: (code: string) => void,
) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const finalRef = useRef("");
  const cbRef = useRef({ onFinal, onError });
  useEffect(() => {
    cbRef.current = { onFinal, onError };
  });
  const supported = getRecognitionCtor() !== null;

  const start = useCallback(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor || recRef.current) return;
    const rec = new Ctor();
    rec.lang = "cs-CZ";
    rec.continuous = false;
    rec.interimResults = true;
    finalRef.current = "";
    rec.onresult = (e) => {
      let interimText = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) finalRef.current += r[0].transcript;
        else interimText += r[0].transcript;
      }
      setInterim(finalRef.current + interimText);
    };
    rec.onerror = (e) => cbRef.current.onError(e.error);
    rec.onend = () => {
      recRef.current = null;
      setListening(false);
      setInterim("");
      const text = finalRef.current.trim();
      finalRef.current = "";
      if (text) cbRef.current.onFinal(text);
    };
    recRef.current = rec;
    setListening(true);
    try {
      rec.start();
    } catch {
      recRef.current = null;
      setListening(false);
      cbRef.current.onError("start-failed");
    }
  }, []);

  const stop = useCallback(() => recRef.current?.stop(), []);

  useEffect(
    () => () => {
      recRef.current?.abort();
      recRef.current = null;
    },
    [],
  );

  return { supported, listening, interim, start, stop };
}
