// Čtení QR z obrazu kamery: nativní BarcodeDetector (Chrome Android), jinak knihovna jsQR.

interface NativeDetector {
  detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>;
}
interface NativeDetectorCtor {
  new (opts?: { formats?: string[] }): NativeDetector;
  getSupportedFormats?: () => Promise<string[]>;
}

export type FrameReader = (video: HTMLVideoElement) => Promise<string | null>;

/** Vytvoří čtečku snímků; `engine` říká, kterou metodu použila (pro ladění a testy). */
export async function createFrameReader(): Promise<{
  read: FrameReader;
  engine: "native" | "jsqr";
}> {
  const Ctor = (globalThis as { BarcodeDetector?: NativeDetectorCtor }).BarcodeDetector;
  if (Ctor) {
    try {
      const formats = (await Ctor.getSupportedFormats?.()) ?? ["qr_code"];
      if (formats.includes("qr_code")) {
        const detector = new Ctor({ formats: ["qr_code"] });
        return {
          engine: "native",
          read: async (video) => (await detector.detect(video))[0]?.rawValue ?? null,
        };
      }
    } catch {
      /* nativní detektor nejde vytvořit – spadne na jsQR */
    }
  }
  const { default: jsQR } = await import("jsqr");
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  return {
    engine: "jsqr",
    read: async (video) => {
      if (!ctx || !video.videoWidth) return null;
      const scale = Math.min(1, 640 / video.videoWidth);
      const w = Math.round(video.videoWidth * scale);
      const h = Math.round(video.videoHeight * scale);
      canvas.width = w;
      canvas.height = h;
      ctx.drawImage(video, 0, 0, w, h);
      const image = ctx.getImageData(0, 0, w, h);
      return jsQR(image.data, w, h, { inversionAttempts: "dontInvert" })?.data ?? null;
    },
  };
}

/** Kamera vyžaduje zabezpečený kontext (HTTPS nebo localhost) a podporu getUserMedia. */
export function cameraSupport(): "ok" | "insecure" | "unsupported" {
  if (typeof window !== "undefined" && window.isSecureContext === false) return "insecure";
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia)
    return typeof window !== "undefined" && window.isSecureContext ? "unsupported" : "insecure";
  return "ok";
}

/** Zpětná vazba při úspěšném přečtení: krátké pípnutí a vibrace (kde to zařízení umí). */
export function scanFeedback() {
  try {
    navigator.vibrate?.(60);
  } catch {
    /* ignoruj */
  }
  try {
    const AC =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return;
    const ac = new AC();
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.frequency.value = 880;
    gain.gain.value = 0.08;
    osc.connect(gain).connect(ac.destination);
    osc.start();
    osc.stop(ac.currentTime + 0.12);
    osc.onended = () => void ac.close();
  } catch {
    /* ignoruj */
  }
}
