// Zpracování textu naskenovaného z QR štítku (nebo ručně zadaného kódu).

/** Vytáhne kód štítku z naskenovaného textu. QR obsahuje přímo `I-000123`, ale tolerujeme i URL
 *  (`…/resolve?code=I-000123`, `…/items/I-000123`) a nadbytečné mezery. */
export function parseScannedText(raw: string): string {
  const text = raw.trim();
  if (!text) return "";
  if (/^https?:\/\//i.test(text)) {
    try {
      const url = new URL(text);
      const fromQuery = url.searchParams.get("code");
      if (fromQuery) return fromQuery.trim();
      const last = url.pathname.split("/").filter(Boolean).pop();
      if (last) return decodeURIComponent(last).trim();
    } catch {
      /* není platná URL – použij text */
    }
  }
  return text;
}

/** Sjednotí kód do tvaru, v jakém ho zná databáze (`i000123` → `I-000123`), pokud se to dá poznat. */
export function normalizeCode(raw: string): string {
  const code = parseScannedText(raw);
  const squashed = code.replace(/[\s_-]+/g, "").toUpperCase();
  const m = /^([IL])(\d{1,9})$/.exec(squashed);
  if (m) return `${m[1]}-${m[2].padStart(6, "0")}`;
  return code.toUpperCase();
}
