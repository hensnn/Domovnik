import type { TFunction } from "i18next";
import { useCallback, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { api_, useApiMutation } from "../../api/hooks";
import type { FileRole, UploadResult } from "../../api/types";

export interface UploadEntry {
  key: number;
  name: string;
  status: "waiting" | "uploading" | "done" | "error";
  error?: string;
  duplicate?: boolean;
}

/** Srozumitelná česká hláška k chybě nahrávání (413 limit, 422/415 nepodporovaný soubor…). */
export function uploadErrorText(err: unknown, t: TFunction): string {
  if (err instanceof ApiError) {
    if (err.status === 413) return t("files.errTooLarge");
    if (err.status === 415) return t("files.errType");
    if (err.status === 422) return `${t("files.errInvalid")} ${err.message}`.trim();
    if (err.status === 403) return t("files.errForbidden");
    return err.message;
  }
  return err instanceof Error ? err.message : t("files.errUnknown");
}

/** Je soubor obrázek (podle MIME, případně přípony – některé telefony posílají prázdné MIME)? */
export function isImageFile(f: { type: string; name: string }): boolean {
  return f.type.startsWith("image/") || /\.(jpe?g|png|webp|heic|heif|gif)$/i.test(f.name);
}

/** Fronta nahrávání: soubory se posílají postupně (zámek primární fotky), stav je vidět po souborech. */
export function useUploadQueue(
  target: { item_id?: string; location_id?: string },
  t: TFunction,
  onFinished?: () => void,
) {
  const [entries, setEntries] = useState<UploadEntry[]>([]);
  const counter = useRef(0);
  const upload = useApiMutation(
    (v: { file: File; role?: FileRole }): Promise<UploadResult> =>
      api_.uploadFile(v.file, { ...target, role: v.role }),
    { invalidate: false },
  );
  const { mutateAsync } = upload;

  const add = useCallback(
    async (files: File[], role?: FileRole) => {
      const fresh: UploadEntry[] = files.map((f) => ({
        key: ++counter.current,
        name: f.name,
        status: "waiting",
      }));
      setEntries((e) => [...fresh, ...e].slice(0, 20));
      const patch = (key: number, p: Partial<UploadEntry>) =>
        setEntries((list) => list.map((x) => (x.key === key ? { ...x, ...p } : x)));
      for (const [i, file] of files.entries()) {
        const key = fresh[i].key;
        patch(key, { status: "uploading" });
        try {
          const res = await mutateAsync({ file, role: isImageFile(file) ? undefined : role });
          patch(key, { status: "done", duplicate: res.duplicate });
        } catch (err) {
          patch(key, { status: "error", error: uploadErrorText(err, t) });
        }
      }
      onFinished?.();
    },
    [mutateAsync, onFinished, t],
  );

  const dismiss = useCallback(
    (key: number) => setEntries((l) => l.filter((x) => x.key !== key)),
    [],
  );
  const active = entries.some((e) => e.status === "waiting" || e.status === "uploading");
  return { entries, add, dismiss, active };
}
