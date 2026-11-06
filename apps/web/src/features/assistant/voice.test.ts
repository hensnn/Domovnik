import { describe, expect, it } from "vitest";

import type { SettingDef } from "../../api/types";
import { plainForSpeech, shouldSpeak, voicePrefs } from "./voice";

const def = (key: string, value: unknown) => ({ key, value }) as SettingDef;

describe("voicePrefs", () => {
  it("čte nastavení voice.* a má rozumné výchozí hodnoty", () => {
    expect(voicePrefs(undefined)).toEqual({
      sttEngine: "browser",
      ttsEngine: "browser",
      ttsSpeed: 1,
      speakReplies: "after_voice",
    });
    expect(
      voicePrefs([
        def("voice.stt_engine", "off"),
        def("voice.tts_engine", "piper"),
        def("voice.tts_speed", 1.4),
        def("voice.speak_replies", "always"),
      ]),
    ).toEqual({ sttEngine: "off", ttsEngine: "piper", ttsSpeed: 1.4, speakReplies: "always" });
  });

  it("neplatnou rychlost nahradí 1", () => {
    expect(voicePrefs([def("voice.tts_speed", "abc")]).ttsSpeed).toBe(1);
  });
});

describe("shouldSpeak", () => {
  const base = voicePrefs(undefined);
  it("řídí se režimem speak_replies a enginem", () => {
    expect(shouldSpeak({ ...base, speakReplies: "never" }, true)).toBe(false);
    expect(shouldSpeak({ ...base, speakReplies: "after_voice" }, true)).toBe(true);
    expect(shouldSpeak({ ...base, speakReplies: "after_voice" }, false)).toBe(false);
    expect(shouldSpeak({ ...base, speakReplies: "always" }, false)).toBe(true);
    expect(shouldSpeak({ ...base, speakReplies: "always", ttsEngine: "off" }, true)).toBe(false);
  });
});

describe("plainForSpeech", () => {
  it("odstraní markdown, aby se nečetly hvězdičky", () => {
    expect(plainForSpeech("**Kladivo** je v [dílně](http://x) `A1`\n\n- ok")).toBe(
      "Kladivo je v dílně A1 - ok",
    );
  });
});
