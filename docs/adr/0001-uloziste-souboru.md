# ADR 0001 – Úložiště souborů (fáze F4)

Stav: přijato. Doplňuje `docs/01-navrh.md` §4.5 a §11.

## Rozhodnutí

1. **Typ určuje obsah.** Magic bytes + dekodér (Pillow, `pillow-heif`); přípona a `Content-Type` od klienta se ignorují. Povoleno: JPEG, PNG, WebP, HEIC/HEIF, GIF (první snímek), PDF. Vše ostatní (SVG, HTML, ZIP, EXE…) → 422.
2. **Obrázky se vždy znovu zakódují** (JPEG; obrázky s průhledností WebP). Výstup nenese žádné EXIF/ICC/XMP ani data za koncem souboru. EXIF orientace se aplikuje, barvy se převedou do sRGB. Bezpečná bílá listina EXIF (výrobce, model, expozice, čas pořízení) jde jen do `files.exif`; GPS tam jen při `photos.strip_gps = false`.
3. **`files.sha256` je otisk nahraných (původních) bajtů**, ne uloženého výstupu. Důvod: opakované nahrání téhož souboru (offline fronta, dvojí výběr) se pozná bez dekódování. Odchylka od návrhu „adresa = hash uloženého souboru“; důsledek je jen to, že dvě různé originální fotky se shodným výstupem se uloží zvlášť.
4. **Rozložení na disku:** `<files_dir>/<ab>/<hash>.<jpg|webp|pdf>`, náhledy `thumbs/<hash>_{256,1024}.webp`, volitelně `originals/<ab>/<hash>.bin` (`photos.keep_original`, API je neservíruje). Do cesty se nikdy nedostane název od klienta.
5. **Náhledy a blurhash synchronně při nahrání** (obrázek je už v paměti a zmenšený; ~desítky ms). Chybějící náhledy se líně doplní při prvním čtení (`ensure_thumbs`). Worker (Procrastinate) zatím nepotřebujeme; OCR PDF zůstává pro pozdější fázi.
6. **Mazání z disku až po commitu** (`run_pending_deletes`); zápis na disk předchází vložení řádku, sirotky uklízí `domovnik files-gc`.
7. **Primární fotka:** každá věc/umístění s alespoň jednou fotkou (role `primary`/`gallery`) má právě jednu vazbu s rolí `primary` (částečný unikátní index, migrace 0004); `items.primary_file_id` ji zrcadlí. Změna primární fotky mění `items.version` (trigger) – klient po změně souborů načte věc znovu.
8. **Mazání souboru:** `DELETE /files/{id}` vrací 409, pokud je soubor připojen; `?force=true` vazby nejdřív odpojí.
9. **Servírování:** obsah je neměnný → `ETag` = hash, `Cache-Control: private, max-age=31536000, immutable`, `nosniff`, `Content-Security-Policy: default-src 'none'; sandbox`. PDF se výchozně stahuje (`attachment`); `?download=false` ho zobrazí.

## Nová nastavení

`photos.max_megapixels` (výchozí 64) a `photos.max_batch_files` (50); existující `photos.*` klíče se používají beze změny.
