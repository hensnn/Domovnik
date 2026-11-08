import clsx from "clsx";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  Focus,
  Maximize,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type { Detection } from "../../api/types";
import { Button, IconButton } from "../../components/ui";
import { type Choice, confidencePercent, confidenceTone } from "../../lib/photos";

const MIN_ZOOM = 1;
const MAX_ZOOM = 8;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Co se po změně přiblížení má udělat s posunem (aby obraz „neutekl“). */
type Pending =
  | { kind: "anchor"; fx: number; fy: number; px: number; py: number }
  | { kind: "center"; fx: number; fy: number };

/**
 * Celoobrazovkový prohlížeč fotky pro kontrolu detailů před uložením: přiblížení kolečkem,
 * štípnutím nebo tlačítky, posun tažením, rámečky nalezených věcí (jdou skrýt),
 * přeskakování mezi nálezy s automatickým přiblížením a potvrzení / odmítnutí přímo tady.
 */
export default function PhotoViewer({
  src,
  detections,
  choices,
  active,
  onSelect,
  onChoice,
  onClose,
}: {
  src: string;
  detections: Detection[];
  choices: Record<string, Choice>;
  active: string | null;
  onSelect: (id: string) => void;
  onChoice: (id: string, choice: Choice) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const scroller = useRef<HTMLDivElement | null>(null);
  const inner = useRef<HTMLDivElement | null>(null);
  const [zoom, setZoom] = useState(1);
  const zoomRef = useRef(1);
  const pending = useRef<Pending | null>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [view, setView] = useState({ w: 0, h: 0 });
  const [showBoxes, setShowBoxes] = useState(true);

  const withBox = useMemo(() => detections.filter((d) => d.bbox), [detections]);
  const activeIdx = useMemo(() => withBox.findIndex((d) => d.id === active), [withBox, active]);
  const current = activeIdx >= 0 ? withBox[activeIdx] : null;

  // velikost okna prohlížeče (kvůli výpočtu „vejde se celé“)
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const measure = () => setView({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const fit = natural && view.w && view.h ? Math.min(view.w / natural.w, view.h / natural.h) : 1;
  const width = natural ? natural.w * fit * zoom : undefined;
  const height = natural ? natural.h * fit * zoom : undefined;

  // po překreslení s novým přiblížením srovná posun
  useLayoutEffect(() => {
    const p = pending.current;
    const sc = scroller.current;
    const box = inner.current;
    if (!p || !sc || !box) return;
    pending.current = null;
    const r = box.getBoundingClientRect();
    if (p.kind === "anchor") {
      sc.scrollLeft += r.left + p.fx * r.width - p.px;
      sc.scrollTop += r.top + p.fy * r.height - p.py;
    } else {
      const s = sc.getBoundingClientRect();
      sc.scrollLeft += r.left + p.fx * r.width - (s.left + s.width / 2);
      sc.scrollTop += r.top + p.fy * r.height - (s.top + s.height / 2);
    }
  }, [zoom, width, height]);

  const applyZoom = useCallback((next: number, clientX?: number, clientY?: number) => {
    const sc = scroller.current;
    const box = inner.current;
    const z = clamp(next, MIN_ZOOM, MAX_ZOOM);
    if (sc && box) {
      const s = sc.getBoundingClientRect();
      const px = clientX ?? s.left + s.width / 2;
      const py = clientY ?? s.top + s.height / 2;
      const r = box.getBoundingClientRect();
      pending.current = {
        kind: "anchor",
        fx: clamp((px - r.left) / r.width, 0, 1),
        fy: clamp((py - r.top) / r.height, 0, 1),
        px,
        py,
      };
    }
    zoomRef.current = z;
    setZoom(z);
  }, []);

  const focusOn = useCallback(
    (d: Detection) => {
      if (!d.bbox || !natural) return;
      const [x, y, w, h] = d.bbox;
      const need = 0.6 * Math.min(view.w / (w * natural.w * fit), view.h / (h * natural.h * fit));
      const z = clamp(Number.isFinite(need) ? need : 2, 1.5, MAX_ZOOM);
      pending.current = { kind: "center", fx: x + w / 2, fy: y + h / 2 };
      zoomRef.current = z;
      setZoom(z);
    },
    [natural, view, fit],
  );

  const go = useCallback(
    (delta: number) => {
      if (!withBox.length) return;
      const base = activeIdx < 0 ? (delta > 0 ? -1 : 0) : activeIdx;
      const next = withBox[(base + delta + withBox.length) % withBox.length];
      onSelect(next.id);
      focusOn(next);
    },
    [withBox, activeIdx, onSelect, focusOn],
  );

  // klávesy: Esc zavře, šipky přeskakují nálezy, + / − / 0 mění přiblížení
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
      else if (e.key === "+" || e.key === "=") applyZoom(zoomRef.current * 1.4);
      else if (e.key === "-") applyZoom(zoomRef.current / 1.4);
      else if (e.key === "0") applyZoom(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, go, applyZoom]);

  // kolečko myši přibližuje k ukazateli (musí být nepasivní, aby šlo zastavit rolování stránky)
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      applyZoom(zoomRef.current * Math.exp(-e.deltaY * 0.0015), e.clientX, e.clientY);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [applyZoom]);

  // zamkne rolování stránky pod prohlížečem
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  // --- gesta: štípnutí dvěma prsty a posun myší (prstem posouvá prohlížeč sám) ---
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ dist: number; zoom: number } | null>(null);
  const drag = useRef<{ moved: boolean; x: number; y: number } | null>(null);
  const suppressClick = useRef(false);

  const dist = () => {
    const [a, b] = [...pointers.current.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  };
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    suppressClick.current = false;
    if (pointers.current.size === 2) {
      pinch.current = { dist: dist() || 1, zoom: zoomRef.current };
      drag.current = null;
    } else if (e.pointerType === "mouse" && e.button === 0) {
      drag.current = { moved: false, x: e.clientX, y: e.clientY };
    }
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!pointers.current.has(e.pointerId)) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const sc = scroller.current;
    if (pointers.current.size === 2 && pinch.current) {
      const [a, b] = [...pointers.current.values()];
      applyZoom(
        pinch.current.zoom * (dist() / pinch.current.dist),
        (a.x + b.x) / 2,
        (a.y + b.y) / 2,
      );
      suppressClick.current = true;
    } else if (drag.current && sc && e.buttons & 1) {
      const dx = e.clientX - drag.current.x;
      const dy = e.clientY - drag.current.y;
      if (!drag.current.moved && Math.hypot(dx, dy) < 5) return;
      if (!drag.current.moved) sc.setPointerCapture(e.pointerId);
      drag.current = { moved: true, x: e.clientX, y: e.clientY };
      suppressClick.current = true;
      sc.scrollLeft -= dx;
      sc.scrollTop -= dy;
    }
  };
  const onPointerEnd = (e: ReactPointerEvent<HTMLDivElement>) => {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
    drag.current = null;
  };

  const choice = current ? (choices[current.id] ?? "pending") : "pending";
  const duplicate = !!current?.matched_item;
  const zoomPct = Math.round(zoom * 100);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("photos.viewer.title")}
      className="fixed inset-0 z-50 flex flex-col bg-black text-white"
    >
      <div className="flex items-center gap-1 border-b border-white/10 px-2 py-2">
        <IconButton
          label={t("photos.viewer.close")}
          onClick={onClose}
          className="!text-white hover:!bg-white/15"
        >
          <X className="size-5" />
        </IconButton>
        <span className="mr-auto truncate px-1 text-sm text-white/70">
          {t("photos.viewer.hint")}
        </span>
        <IconButton
          label={t("photos.viewer.zoomOut")}
          onClick={() => applyZoom(zoom / 1.4)}
          disabled={zoom <= MIN_ZOOM}
          className="!text-white hover:!bg-white/15"
        >
          <ZoomOut className="size-5" />
        </IconButton>
        <span className="w-12 text-center text-sm tabular-nums" aria-live="polite">
          {zoomPct} %
        </span>
        <IconButton
          label={t("photos.viewer.zoomIn")}
          onClick={() => applyZoom(zoom * 1.4)}
          disabled={zoom >= MAX_ZOOM}
          className="!text-white hover:!bg-white/15"
        >
          <ZoomIn className="size-5" />
        </IconButton>
        <IconButton
          label={t("photos.viewer.fit")}
          onClick={() => applyZoom(1)}
          className="!text-white hover:!bg-white/15"
        >
          <Maximize className="size-5" />
        </IconButton>
        <IconButton
          label={showBoxes ? t("photos.viewer.hideBoxes") : t("photos.viewer.showBoxes")}
          aria-pressed={showBoxes}
          onClick={() => setShowBoxes((v) => !v)}
          className="!text-white hover:!bg-white/15"
        >
          {showBoxes ? <Eye className="size-5" /> : <EyeOff className="size-5" />}
        </IconButton>
      </div>

      <div
        ref={scroller}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
        onDoubleClick={(e) => applyZoom(zoom > 1.5 ? 1 : 3, e.clientX, e.clientY)}
        className={clsx(
          "flex min-h-0 flex-1 touch-pan-x touch-pan-y overflow-auto",
          zoom > 1 && "cursor-grab active:cursor-grabbing",
        )}
      >
        <div
          ref={inner}
          className="relative m-auto shrink-0 select-none"
          style={width ? { width, height } : undefined}
        >
          <img
            src={src}
            alt={t("photos.photoAlt")}
            draggable={false}
            onLoad={(e) =>
              setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })
            }
            className={clsx("block", width ? "size-full" : "max-h-full max-w-full")}
          />
          {showBoxes &&
            detections.map((d, i) => {
              if (!d.bbox) return null;
              const [x, y, w, h] = d.bbox;
              const c = choices[d.id] ?? "pending";
              const tone =
                c === "accept"
                  ? "border-emerald-400"
                  : c === "merge"
                    ? "border-sky-400"
                    : c === "reject"
                      ? "border-slate-300 border-dashed opacity-60"
                      : confidenceTone(d.confidence) === "green"
                        ? "border-emerald-300"
                        : confidenceTone(d.confidence) === "amber"
                          ? "border-amber-300"
                          : "border-red-400";
              return (
                <button
                  key={d.id}
                  type="button"
                  aria-label={t("photos.boxLabel", { n: i + 1, name: d.suggested.name || d.label })}
                  aria-pressed={active === d.id}
                  onClickCapture={(e) => {
                    if (suppressClick.current) e.stopPropagation();
                  }}
                  onClick={() => onSelect(d.id)}
                  style={{
                    left: `${x * 100}%`,
                    top: `${y * 100}%`,
                    width: `${w * 100}%`,
                    height: `${h * 100}%`,
                  }}
                  className={clsx(
                    "absolute rounded-sm border-2 focus-visible:outline-2 focus-visible:outline-white",
                    tone,
                    active === d.id && "z-10 !border-4 bg-white/10",
                  )}
                >
                  <span className="absolute -left-0.5 -top-0.5 rounded-br bg-black/80 px-1 text-[10px] font-bold leading-4">
                    {i + 1}
                  </span>
                </button>
              );
            })}
        </div>
      </div>

      <div className="space-y-2 border-t border-white/10 px-3 py-2">
        <div className="flex items-center gap-2">
          <IconButton
            label={t("photos.viewer.prev")}
            onClick={() => go(-1)}
            disabled={!withBox.length}
            className="!text-white hover:!bg-white/15"
          >
            <ChevronLeft className="size-5" />
          </IconButton>
          <div className="min-w-0 flex-1 text-center">
            {current ? (
              <>
                <div className="truncate font-medium">
                  {detections.indexOf(current) + 1}. {current.suggested.name || current.label}
                </div>
                <div className="truncate text-xs text-white/60">
                  {t("photos.viewer.position", { n: activeIdx + 1, total: withBox.length })} ·{" "}
                  {confidencePercent(current.confidence)}
                  {current.description ? ` · ${current.description}` : ""}
                </div>
              </>
            ) : (
              <p className="text-sm text-white/60">
                {withBox.length ? t("photos.viewer.pickBox") : t("photos.viewer.noBoxes")}
              </p>
            )}
          </div>
          <IconButton
            label={t("photos.viewer.next")}
            onClick={() => go(1)}
            disabled={!withBox.length}
            className="!text-white hover:!bg-white/15"
          >
            <ChevronRight className="size-5" />
          </IconButton>
        </div>
        {current && (
          <>
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Button size="sm" onClick={() => focusOn(current)}>
                <Focus className="size-4" /> {t("photos.viewer.focus")}
              </Button>
              {!duplicate && (
                <Button
                  size="sm"
                  variant={choice === "accept" ? "primary" : "secondary"}
                  aria-pressed={choice === "accept"}
                  onClick={() => onChoice(current.id, choice === "accept" ? "pending" : "accept")}
                >
                  <Check className="size-4" /> {t("photos.accept")}
                </Button>
              )}
              <Button
                size="sm"
                variant={choice === "reject" ? "danger" : "secondary"}
                aria-pressed={choice === "reject"}
                onClick={() => onChoice(current.id, choice === "reject" ? "pending" : "reject")}
              >
                <X className="size-4" /> {t("photos.reject")}
              </Button>
            </div>
            {duplicate && (
              <p className="text-center text-xs text-amber-300">{t("photos.viewer.duplicate")}</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
