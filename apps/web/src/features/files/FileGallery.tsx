import clsx from "clsx";
import {
  Camera,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileText,
  Loader2,
  Star,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { type DragEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  api_,
  useApiMutation,
  useInvalidateData,
  useItemFiles,
  useLocationFiles,
} from "../../api/hooks";
import type { FileLink, FileRole } from "../../api/types";
import { Thumb, thumbUrl } from "../../components/Thumb";
import {
  Badge,
  Button,
  IconButton,
  Input,
  Modal,
  Select,
  Spinner,
  errorMessage,
  useToast,
} from "../../components/ui";
import { formatBytes } from "../../lib/format";
import { isImageFile, useUploadQueue } from "./uploads";

const DOC_ROLES: FileRole[] = ["manual", "receipt", "warranty", "other"];

/** Galerie fotek + seznam dokumentů věci nebo umístění, s nahráváním (foťák, soubor, drag&drop). */
export default function FileGallery({
  kind,
  id,
  canWrite,
}: {
  kind: "item" | "location";
  id: string;
  canWrite: boolean;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const itemQ = useItemFiles(kind === "item" ? id : undefined);
  const locQ = useLocationFiles(kind === "location" ? id : undefined);
  const q = kind === "item" ? itemQ : locQ;
  const invalidate = useInvalidateData();
  const links = q.data ?? [];
  const photos = links.filter((l) => l.file.kind === "photo");
  const docs = links.filter((l) => l.file.kind !== "photo");

  const [docRole, setDocRole] = useState<FileRole>("manual");
  const [dragging, setDragging] = useState(false);
  const [lightbox, setLightbox] = useState<number | null>(null);
  const [toDelete, setToDelete] = useState<FileLink | null>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const pickRef = useRef<HTMLInputElement>(null);

  const queue = useUploadQueue(
    kind === "item" ? { item_id: id } : { location_id: id },
    t,
    invalidate,
  );

  const handleFiles = (list: FileList | File[] | null) => {
    const files = Array.from(list ?? []);
    if (!files.length) return;
    const ok = files.filter(
      (f) => isImageFile(f) || f.type === "application/pdf" || /\.pdf$/i.test(f.name),
    );
    if (ok.length < files.length)
      toast(t("files.skippedUnsupported", { count: files.length - ok.length }), "error");
    if (ok.length) void queue.add(ok, docRole);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (canWrite) handleFiles(e.dataTransfer.files);
  };

  const setPrimary = useApiMutation(
    (l: FileLink) => api_.updateFileLink(l.id, { is_primary: true }),
    {
      onSuccess: () => toast(t("files.primarySet")),
    },
  );
  const saveCaption = useApiMutation(
    (v: { link: FileLink; caption: string }) =>
      api_.updateFileLink(v.link.id, { caption: v.caption.trim() || null }),
    { onSuccess: () => toast(t("common.saved")) },
  );
  const changeRole = useApiMutation((v: { link: FileLink; role: FileRole }) =>
    api_.updateFileLink(v.link.id, { role: v.role }),
  );
  const detach = useApiMutation((l: FileLink) => api_.deleteFileLink(l.id), {
    onSuccess: () => {
      toast(t("files.removed"));
      setToDelete(null);
      setLightbox((i) =>
        i === null ? null : photos.length <= 1 ? null : Math.min(i, photos.length - 2),
      );
    },
  });

  if (q.isPending) return <Spinner />;
  if (q.isError)
    return (
      <p role="alert" className="text-sm text-red-600">
        {errorMessage(q.error)}
      </p>
    );

  return (
    <section className="space-y-3" aria-label={t("files.title")}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold">
          {t("files.title")}{" "}
          <span className="text-sm font-normal text-slate-500">{links.length}</span>
        </h3>
      </div>

      {photos.length === 0 && docs.length === 0 && (
        <p className="text-sm text-slate-500">{t("files.empty")}</p>
      )}

      {photos.length > 0 && (
        <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {photos.map((l, i) => (
            <li key={l.id} className="relative">
              <button
                onClick={() => setLightbox(i)}
                aria-label={t("files.open", { name: l.caption ?? l.file.original_name ?? "" })}
                className="block aspect-square w-full overflow-hidden rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500"
              >
                <Thumb fileId={l.file.id} className="size-full" alt={l.caption ?? ""} />
              </button>
              {l.is_primary && (
                <span className="pointer-events-none absolute left-1 top-1 rounded-full bg-amber-500 p-1 text-white">
                  <Star className="size-3 fill-current" aria-label={t("files.primary")} />
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {docs.length > 0 && (
        <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
          {docs.map((l) => (
            <li key={l.id} className="flex flex-wrap items-center gap-2 p-2 text-sm">
              <FileText className="size-5 shrink-0 text-slate-500" aria-hidden />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">
                  {l.caption || l.file.original_name || t("files.document")}
                </div>
                <div className="text-xs text-slate-500">{formatBytes(l.file.size_bytes)}</div>
              </div>
              {canWrite ? (
                <Select
                  aria-label={t("files.docRole")}
                  value={l.role}
                  onChange={(e) => changeRole.mutate({ link: l, role: e.target.value as FileRole })}
                  className="!w-auto !py-1"
                >
                  {DOC_ROLES.map((r) => (
                    <option key={r} value={r}>
                      {t(`files.role.${r}`)}
                    </option>
                  ))}
                </Select>
              ) : (
                <Badge>{t(`files.role.${l.role}`, { defaultValue: l.role })}</Badge>
              )}
              <a
                href={`/api/v1/files/${l.file.id}?download=false`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
              >
                <ExternalLink className="size-3.5" /> {t("files.openDoc")}
              </a>
              {canWrite && (
                <IconButton label={t("files.remove")} onClick={() => setToDelete(l)}>
                  <Trash2 className="size-4" />
                </IconButton>
              )}
            </li>
          ))}
        </ul>
      )}

      {canWrite && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={clsx(
            "space-y-2 rounded-xl border-2 border-dashed p-3 text-sm",
            dragging
              ? "border-brand-500 bg-brand-50 dark:bg-brand-700/10"
              : "border-slate-300 dark:border-slate-700",
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={() => cameraRef.current?.click()}>
              <Camera className="size-4" /> {t("files.takePhoto")}
            </Button>
            <Button size="sm" onClick={() => pickRef.current?.click()}>
              <Upload className="size-4" /> {t("files.pickFile")}
            </Button>
            <label className="ml-auto flex items-center gap-2 text-xs text-slate-500">
              {t("files.docRole")}
              <Select
                value={docRole}
                onChange={(e) => setDocRole(e.target.value as FileRole)}
                className="!w-auto !py-1"
              >
                {DOC_ROLES.map((r) => (
                  <option key={r} value={r}>
                    {t(`files.role.${r}`)}
                  </option>
                ))}
              </Select>
            </label>
          </div>
          <p className="text-xs text-slate-500">{t("files.dropHint")}</p>
          <input
            ref={cameraRef}
            type="file"
            accept="image/*"
            capture="environment"
            multiple
            hidden
            data-testid="camera-input"
            onChange={(e) => {
              handleFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <input
            ref={pickRef}
            type="file"
            accept="image/*,application/pdf"
            multiple
            hidden
            data-testid="file-input"
            onChange={(e) => {
              handleFiles(e.target.files);
              e.target.value = "";
            }}
          />
          {queue.entries.length > 0 && (
            <ul className="space-y-1" aria-label={t("files.uploads")}>
              {queue.entries.map((u) => (
                <li key={u.key} className="flex items-center gap-2 text-xs">
                  {u.status === "uploading" || u.status === "waiting" ? (
                    <Loader2
                      className="size-3.5 shrink-0 animate-spin text-brand-600"
                      aria-hidden
                    />
                  ) : u.status === "done" ? (
                    <span className="text-emerald-600" aria-hidden>
                      ✓
                    </span>
                  ) : (
                    <span className="text-red-600" aria-hidden>
                      ✕
                    </span>
                  )}
                  <span className="min-w-0 flex-1 truncate">{u.name}</span>
                  <span
                    role={u.status === "error" ? "alert" : "status"}
                    className={u.status === "error" ? "text-red-600" : "text-slate-500"}
                  >
                    {u.status === "error"
                      ? u.error
                      : u.status === "done"
                        ? u.duplicate
                          ? t("files.duplicate")
                          : t("files.uploaded")
                        : u.status === "uploading"
                          ? t("files.uploading")
                          : t("files.waiting")}
                  </span>
                  {(u.status === "done" || u.status === "error") && (
                    <button
                      aria-label={t("common.remove", { name: u.name })}
                      onClick={() => queue.dismiss(u.key)}
                    >
                      <X className="size-3.5" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {lightbox !== null && photos[lightbox] && (
        <Lightbox
          key={photos[lightbox].id}
          photos={photos}
          index={lightbox}
          canWrite={canWrite}
          onIndex={setLightbox}
          onClose={() => setLightbox(null)}
          onPrimary={(l) => setPrimary.mutate(l)}
          onCaption={(l, caption) => saveCaption.mutate({ link: l, caption })}
          onDelete={setToDelete}
          saving={setPrimary.isPending || saveCaption.isPending}
        />
      )}

      <Modal
        open={!!toDelete}
        onClose={() => setToDelete(null)}
        title={t("files.removeTitle")}
        footer={
          <>
            <Button onClick={() => setToDelete(null)}>{t("common.cancel")}</Button>
            <Button
              variant="danger"
              disabled={detach.isPending}
              onClick={() => toDelete && detach.mutate(toDelete)}
            >
              {t("files.remove")}
            </Button>
          </>
        }
      >
        <p className="text-sm">{t("files.removeHint")}</p>
        {detach.isError && (
          <p role="alert" className="mt-2 text-sm text-red-600">
            {errorMessage(detach.error)}
          </p>
        )}
      </Modal>
    </section>
  );
}

function Lightbox({
  photos,
  index,
  canWrite,
  onIndex,
  onClose,
  onPrimary,
  onCaption,
  onDelete,
  saving,
}: {
  photos: FileLink[];
  index: number;
  canWrite: boolean;
  onIndex: (i: number) => void;
  onClose: () => void;
  onPrimary: (l: FileLink) => void;
  onCaption: (l: FileLink, caption: string) => void;
  onDelete: (l: FileLink) => void;
  saving: boolean;
}) {
  const { t } = useTranslation();
  const link = photos[index];
  const [caption, setCaption] = useState(link.caption ?? "");
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => closeRef.current?.focus(), []);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft" && index > 0) onIndex(index - 1);
      else if (e.key === "ArrowRight" && index < photos.length - 1) onIndex(index + 1);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [index, photos.length, onIndex, onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("files.viewer")}
      className="fixed inset-0 z-50 flex flex-col bg-black/90 text-white"
    >
      <div className="flex items-center justify-between gap-2 p-2">
        <span className="text-sm">
          {index + 1} / {photos.length}
          {link.is_primary && (
            <span className="ml-2 inline-flex items-center gap-1 text-amber-400">
              <Star className="size-4 fill-current" aria-hidden /> {t("files.primary")}
            </span>
          )}
        </span>
        <div className="flex items-center gap-1">
          <a
            href={link.file.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm hover:bg-white/10"
          >
            <ExternalLink className="size-4" /> {t("files.original")}
          </a>
          <button
            ref={closeRef}
            aria-label={t("files.close")}
            onClick={onClose}
            className="rounded-lg p-2 hover:bg-white/10"
          >
            <X className="size-5" />
          </button>
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1 items-center justify-center">
        <img
          src={thumbUrl(link.file.id, 1024)}
          alt={link.caption ?? link.file.original_name ?? ""}
          className="max-h-full max-w-full object-contain"
        />
        {index > 0 && (
          <button
            aria-label={t("common.prev")}
            onClick={() => onIndex(index - 1)}
            className="absolute left-1 rounded-full bg-black/50 p-2 hover:bg-black/70"
          >
            <ChevronLeft className="size-6" />
          </button>
        )}
        {index < photos.length - 1 && (
          <button
            aria-label={t("common.next")}
            onClick={() => onIndex(index + 1)}
            className="absolute right-1 rounded-full bg-black/50 p-2 hover:bg-black/70"
          >
            <ChevronRight className="size-6" />
          </button>
        )}
      </div>

      <div className="space-y-2 bg-white p-3 text-slate-900 dark:bg-slate-900 dark:text-slate-100">
        {canWrite ? (
          <div className="flex flex-wrap items-center gap-2">
            <Input
              aria-label={t("files.caption")}
              placeholder={t("files.captionPlaceholder")}
              value={caption}
              maxLength={1000}
              onChange={(e) => setCaption(e.target.value)}
              className="min-w-0 flex-1"
            />
            <Button
              size="sm"
              disabled={saving || caption === (link.caption ?? "")}
              onClick={() => onCaption(link, caption)}
            >
              {t("common.save")}
            </Button>
            {!link.is_primary && (
              <Button size="sm" disabled={saving} onClick={() => onPrimary(link)}>
                <Star className="size-4" /> {t("files.makePrimary")}
              </Button>
            )}
            <Button size="sm" onClick={() => onDelete(link)}>
              <Trash2 className="size-4" /> {t("files.remove")}
            </Button>
          </div>
        ) : (
          link.caption && <p className="text-sm">{link.caption}</p>
        )}
      </div>
    </div>
  );
}
