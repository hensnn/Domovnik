import clsx from "clsx";
import { ImageIcon } from "lucide-react";
import { useState } from "react";

export const thumbUrl = (fileId: string, size: 256 | 1024 = 256) =>
  `/api/v1/files/${fileId}/thumb?size=${size}`;

/** Čtvercový náhled fotky (lazy loading); bez fotky nebo při chybě se ukáže zástupná ikona. */
export function Thumb({
  fileId,
  size = 256,
  className,
  alt = "",
}: {
  fileId: string | null | undefined;
  size?: 256 | 1024;
  className?: string;
  alt?: string;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const broken = !fileId || failed === fileId;
  return (
    <span
      className={clsx(
        "relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-lg bg-slate-100 text-slate-400 dark:bg-slate-800",
        className ?? "size-10",
      )}
    >
      {broken ? (
        <ImageIcon className="size-1/2" aria-hidden />
      ) : (
        <img
          src={thumbUrl(fileId, size)}
          alt={alt}
          loading="lazy"
          decoding="async"
          onError={() => setFailed(fileId)}
          className="size-full object-cover"
        />
      )}
    </span>
  );
}
