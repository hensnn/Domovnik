import { Keyboard, ScanLine } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Input } from "../../components/ui";
import { cameraSupport, createFrameReader, scanFeedback } from "./qrDetect";

type State = "starting" | "scanning" | "insecure" | "unsupported" | "denied" | "error";

const SAME_CODE_PAUSE_MS = 2500;

/** Kamera + ruční zadání kódu. `onCode` dostane surový text (volající ho normalizuje). */
export default function QrScanner({
  active = true,
  onCode,
  className,
}: {
  active?: boolean;
  onCode: (raw: string) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<State>("starting");
  const [manual, setManual] = useState("");
  const onCodeRef = useRef(onCode);
  useEffect(() => {
    onCodeRef.current = onCode;
  }, [onCode]);

  useEffect(() => {
    if (!active) return;
    const support = cameraSupport();
    if (support !== "ok") {
      // stav kamery se odvozuje z prostředí prohlížeče, ne z dat – nastavení je tu záměrné
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setState(support);
      return;
    }
    const videoEl = videoRef.current;
    let stopped = false;
    let stream: MediaStream | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let last = { text: "", at: 0 };

    void (async () => {
      setState("starting");
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" } },
          audio: false,
        });
      } catch (e) {
        if (!stopped) setState((e as DOMException).name === "NotAllowedError" ? "denied" : "error");
        return;
      }
      if (stopped) {
        stream.getTracks().forEach((tr) => tr.stop());
        return;
      }
      const video = videoRef.current;
      if (!video) return;
      video.srcObject = stream;
      try {
        await video.play();
        const { read } = await createFrameReader();
        if (stopped) return;
        setState("scanning");
        const tick = async () => {
          if (stopped) return;
          try {
            const text = await read(video);
            const now = Date.now();
            if (text && (text !== last.text || now - last.at > SAME_CODE_PAUSE_MS)) {
              last = { text, at: now };
              scanFeedback();
              onCodeRef.current(text);
            }
          } catch {
            /* jednotlivý snímek se nepodařil – zkus další */
          }
          timer = setTimeout(() => void tick(), 150);
        };
        void tick();
      } catch {
        if (!stopped) setState("error");
      }
    })();

    return () => {
      stopped = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((tr) => tr.stop());
      if (videoEl) videoEl.srcObject = null;
    };
  }, [active]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!manual.trim()) return;
    onCode(manual);
    setManual("");
  };

  const problem =
    state === "insecure" || state === "unsupported" || state === "denied" || state === "error";

  return (
    <div className={className}>
      <div className="relative aspect-square max-h-[55dvh] w-full overflow-hidden rounded-2xl bg-slate-900 sm:aspect-video">
        <video
          ref={videoRef}
          muted
          playsInline
          aria-label={t("scan.cameraView")}
          className="size-full object-cover"
        />
        {state === "scanning" && (
          <div aria-hidden className="pointer-events-none absolute inset-0 grid place-items-center">
            <div className="size-2/3 rounded-2xl border-4 border-white/80 shadow-[0_0_0_999px_rgba(15,23,42,0.35)]" />
          </div>
        )}
        {!problem && state === "starting" && (
          <p className="absolute inset-0 grid place-items-center text-sm text-white">
            {t("scan.starting")}
          </p>
        )}
        {problem && (
          <div
            role="alert"
            className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4 text-center text-sm text-white"
          >
            <ScanLine className="size-8 opacity-70" />
            <p>{t(`scan.problem.${state}`)}</p>
          </div>
        )}
      </div>

      <form onSubmit={submit} className="mt-3 flex gap-2">
        <label className="sr-only" htmlFor="manual-code">
          {t("scan.manualLabel")}
        </label>
        <Input
          id="manual-code"
          value={manual}
          onChange={(e) => setManual(e.target.value)}
          placeholder={t("scan.manualPlaceholder")}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          className="font-mono"
        />
        <Button type="submit" variant="primary" disabled={!manual.trim()}>
          <Keyboard className="size-4" /> {t("scan.manualSubmit")}
        </Button>
      </form>
    </div>
  );
}
