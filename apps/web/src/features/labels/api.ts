import { buildQuery, get } from "../../api/client";

export interface ResolveResult {
  type: "item" | "location";
  id: string;
  name: string;
  label_code: string;
  full_name: string | null;
  deleted: boolean;
}

export const resolveCode = (code: string) => get<ResolveResult>("/resolve", { code });

export type PageFormat = "A4_3x8" | "A4_2x5" | "A4_4x12";

/** Mřížka archu (sloupce × řádky) a popis rozměru štítku. */
export const PAGE_FORMATS: Record<PageFormat, { cols: number; rows: number; size: string }> = {
  A4_3x8: { cols: 3, rows: 8, size: "70 × 37 mm" },
  A4_2x5: { cols: 2, rows: 5, size: "105 × 59 mm" },
  A4_4x12: { cols: 4, rows: 12, size: "52 × 25 mm" },
};

/** GET adresa je omezená délkou řádku požadavku – víc ID najednou netiskneme. */
export const MAX_LABELS_PER_PRINT = 300;

export function labelsPdfUrl(opts: {
  kind: "item" | "location";
  ids: string[];
  format: PageFormat;
  start: number;
  showPath: boolean;
}): string {
  const q = buildQuery({
    kind: opts.kind,
    ids: opts.ids.slice(0, MAX_LABELS_PER_PRINT).join(","),
    format: opts.format,
    start: opts.start,
    show_path: opts.showPath,
  });
  return `/api/v1/labels/pdf${q}`;
}

/** Počet stran PDF při tisku `count` štítků od buňky `start`. */
export function pageCount(count: number, format: PageFormat, start: number): number {
  const { cols, rows } = PAGE_FORMATS[format];
  return Math.max(1, Math.ceil((start + count) / (cols * rows)));
}
