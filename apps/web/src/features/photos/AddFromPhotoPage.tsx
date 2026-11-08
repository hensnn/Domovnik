import type { TFunction } from "i18next";
import { useQuery } from "@tanstack/react-query";
import { Camera, CheckCircle2, ImagePlus, Loader2, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import { api_, useAiStatus, useApiMutation, useItem } from "../../api/hooks";
import type { CommitResult, DetectionDecision } from "../../api/types";
import { LocationSelect } from "../../components/Pickers";
import { Button, Card, Field, Textarea, errorMessage } from "../../components/ui";
import { useCurrentLocation } from "../../lib/currentLocation";
import { POLL_INTERVAL_MS, POLL_TIMEOUT_MS, normalizeAnalysis } from "../../lib/photos";
import { useAuth } from "../auth/AuthProvider";
import ChangeSetCard, { changeSetError } from "../assistant/ChangeSetCard";
import { uploadErrorText } from "../files/uploads";
import ReviewScreen from "./ReviewScreen";

type Phase = "pick" | "uploading" | "starting" | "analyzing";

export default function AddFromPhotoPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [params] = useSearchParams();
  const [currentLoc] = useCurrentLocation();
  const status = useAiStatus();

  const [file, setFile] = useState<File | null>(null);
  const [locationId, setLocationId] = useState<string | null>(
    params.get("location_id") ?? currentLoc,
  );
  const [hint, setHint] = useState("");
  const [phase, setPhase] = useState<Phase>("pick");
  const [fileId, setFileId] = useState<string | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const [result, setResult] = useState<CommitResult | null>(null);
  const [commitError, setCommitError] = useState<string | null>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const pickRef = useRef<HTMLInputElement>(null);

  const preview = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => (preview ? URL.revokeObjectURL(preview) : undefined), [preview]);

  // --- dotazování na výsledek analýzy ---
  const analyzing = phase === "analyzing" && !!analysisId && !timedOut;
  const poll = useQuery({
    queryKey: ["photo-analysis", analysisId],
    queryFn: ({ signal }) => api_.getAnalysis(analysisId!, signal),
    enabled: analyzing,
    retry: 2,
    gcTime: 0,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "done" || s === "failed" ? false : POLL_INTERVAL_MS;
    },
  });
  const analysis = poll.data ? normalizeAnalysis(poll.data) : null;
  const finished = analysis?.status === "done" || analysis?.status === "failed";

  useEffect(() => {
    if (!analyzing || finished) return;
    const id = setTimeout(() => setTimedOut(true), POLL_TIMEOUT_MS);
    return () => clearTimeout(id);
  }, [analyzing, finished, analysisId]);

  const commit = useApiMutation(
    (decisions: DetectionDecision[]) => api_.commitAnalysis(analysisId!, decisions),
    {
      onSuccess: (res) => {
        setResult(res);
        setCommitError(null);
      },
    },
  );

  if (!can("items:write")) {
    return <p className="p-4 text-sm text-slate-500">{t("photos.noPermission")}</p>;
  }

  const reset = () => {
    setFile(null);
    setHint("");
    setPhase("pick");
    setFileId(null);
    setAnalysisId(null);
    setError(null);
    setTimedOut(false);
    setResult(null);
    setCommitError(null);
    commit.reset();
  };

  const analyze = async (existingFileId?: string) => {
    setError(null);
    setTimedOut(false);
    try {
      let id = existingFileId ?? fileId;
      if (!id) {
        if (!file) return;
        setPhase("uploading");
        const up = await api_.uploadFile(file);
        id = up.file.id;
        setFileId(id);
      }
      setPhase("starting");
      const started = await api_.analyzePhoto({
        file_id: id,
        context_location_id: locationId ?? undefined,
        hint: hint.trim() || undefined,
      });
      setAnalysisId(started.id);
      setPhase("analyzing");
    } catch (err) {
      setPhase("pick");
      setError(analysisErrorText(err, t));
    }
  };

  const onPicked = (files: FileList | null) => {
    const f = files?.[0];
    if (!f) return;
    setFile(f);
    setFileId(null);
    setAnalysisId(null);
    setError(null);
  };

  // --- výsledek ---
  if (result) {
    return (
      <Shell title={t("photos.doneTitle")}>
        <DoneView result={result} onAgain={reset} />
      </Shell>
    );
  }

  // --- revize ---
  if (analyzing && analysis?.status === "done") {
    return (
      <Shell title={t("photos.reviewTitle")} wide>
        <ReviewScreen
          analysis={analysis}
          committing={commit.isPending}
          error={commitError}
          onCancel={reset}
          onCommit={(decisions) => {
            setCommitError(null);
            commit.mutate(decisions, {
              onError: (e) => setCommitError(changeSetError(e, t)),
            });
          }}
        />
      </Shell>
    );
  }

  // --- selhání / čekání ---
  if (analyzing && analysis?.status === "failed") {
    return (
      <Shell title={t("photos.title")}>
        <FailedView
          message={analysis.error || t("photos.failedUnknown")}
          onRetry={() => {
            setAnalysisId(null);
            void analyze(analysis.file_id);
          }}
          onBack={reset}
        />
      </Shell>
    );
  }
  if (timedOut || (analyzing && poll.isError)) {
    return (
      <Shell title={t("photos.title")}>
        <FailedView
          message={poll.isError ? errorMessage(poll.error) : t("photos.timeout")}
          onRetry={() => {
            if (poll.isError) void poll.refetch();
            setTimedOut(false);
          }}
          onBack={reset}
        />
      </Shell>
    );
  }
  if (phase !== "pick") {
    const label =
      phase === "uploading"
        ? t("photos.uploading")
        : phase === "starting"
          ? t("photos.starting")
          : analysis?.status === "running"
            ? t("photos.running")
            : t("photos.queued");
    return (
      <Shell title={t("photos.title")}>
        <Card className="flex flex-col items-center gap-3 py-10 text-center">
          {preview && <img src={preview} alt="" className="max-h-48 rounded-lg object-contain" />}
          <Loader2 className="size-8 animate-spin text-brand-600" aria-hidden />
          <p role="status" className="font-medium">
            {label}
          </p>
          <p className="max-w-sm text-sm text-slate-500">{t("photos.waitHint")}</p>
        </Card>
      </Shell>
    );
  }

  // --- výběr fotky ---
  const st = status.data;
  return (
    <Shell title={t("photos.title")}>
      <div className="space-y-4">
        <p className="text-sm text-slate-500">{t("photos.intro")}</p>
        {st && st.enabled && !st.configured && (
          <p role="status" className="rounded-lg bg-amber-50 p-3 text-sm dark:bg-amber-950/40">
            {t("assistant.notConfigured")}{" "}
            <Link
              to="/settings?tab=ai"
              className="font-medium text-brand-700 underline dark:text-brand-100"
            >
              {t("assistant.openSettings")}
            </Link>
          </p>
        )}

        <Card className="space-y-4">
          {preview ? (
            <div className="space-y-2 text-center">
              <img
                src={preview}
                alt={t("photos.photoAlt")}
                className="mx-auto max-h-64 rounded-lg object-contain"
              />
              <p className="truncate text-xs text-slate-500">{file?.name}</p>
            </div>
          ) : null}

          <div className="grid gap-2 sm:grid-cols-2">
            <Button
              variant={file ? "secondary" : "primary"}
              className="!py-4"
              onClick={() => cameraRef.current?.click()}
            >
              <Camera className="size-5" /> {t("files.takePhoto")}
            </Button>
            <Button className="!py-4" onClick={() => pickRef.current?.click()}>
              <ImagePlus className="size-5" /> {t("photos.pickPhoto")}
            </Button>
          </div>
          <input
            ref={cameraRef}
            type="file"
            accept="image/*"
            capture="environment"
            hidden
            data-testid="camera-input"
            onChange={(e) => {
              onPicked(e.target.files);
              e.target.value = "";
            }}
          />
          <input
            ref={pickRef}
            type="file"
            accept="image/*"
            hidden
            data-testid="file-input"
            onChange={(e) => {
              onPicked(e.target.files);
              e.target.value = "";
            }}
          />

          <Field label={t("photos.locationLabel")} hint={t("photos.locationHint")}>
            {(id) => (
              <LocationSelect
                id={id}
                value={locationId}
                onChange={setLocationId}
                emptyLabel={t("photos.locationNone")}
              />
            )}
          </Field>
          <Field label={t("photos.hintLabel")} hint={t("photos.hintHelp")}>
            {(id) => (
              <Textarea
                id={id}
                rows={2}
                maxLength={500}
                value={hint}
                onChange={(e) => setHint(e.target.value)}
                placeholder={t("photos.hintPlaceholder")}
              />
            )}
          </Field>

          {error && (
            <p role="alert" className="text-sm text-red-600">
              {error}
            </p>
          )}
          <Button
            variant="primary"
            className="w-full !py-3"
            disabled={!file}
            onClick={() => void analyze()}
          >
            {t("photos.analyze")}
          </Button>
        </Card>
      </div>
    </Shell>
  );
}

function Shell({
  title,
  children,
  wide,
}: {
  title: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={`mx-auto space-y-3 p-3 md:p-5 ${wide ? "max-w-none" : "max-w-2xl"}`}>
      <h1 className="text-xl font-bold">{title}</h1>
      {children}
    </div>
  );
}

function FailedView({
  message,
  onRetry,
  onBack,
}: {
  message: string;
  onRetry: () => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Card className="space-y-3">
      <p role="alert" className="text-sm text-red-600">
        {message}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={onRetry}>
          <RefreshCw className="size-4" /> {t("photos.retry")}
        </Button>
        <Button onClick={onBack}>{t("photos.otherPhoto")}</Button>
      </div>
    </Card>
  );
}

function ItemLink({ id }: { id: string }) {
  const { data } = useItem(id);
  return (
    <li>
      <Link to={`/items/${id}`} className="text-brand-700 underline dark:text-brand-100">
        {data?.name ?? "…"}
      </Link>
      {data && <span className="ml-2 font-mono text-xs text-slate-500">{data.label_code}</span>}
    </li>
  );
}

function DoneView({ result, onAgain }: { result: CommitResult; onAgain: () => void }) {
  const { t } = useTranslation();
  const created = result.created_item_ids ?? [];
  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <p className="flex items-center gap-2 font-medium">
          <CheckCircle2 className="size-5 text-emerald-600" aria-hidden />
          {t("photos.created", { count: created.length })}
        </p>
        {created.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {created.map((id) => (
              <ItemLink key={id} id={id} />
            ))}
          </ul>
        )}
      </Card>
      <ChangeSetCard changeSet={result.change_set} />
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={onAgain}>
          <Camera className="size-4" /> {t("photos.another")}
        </Button>
        <Link
          to="/items"
          className="inline-flex items-center rounded-lg border border-slate-300 px-3.5 py-2 text-sm font-medium hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
        >
          {t("photos.showItems")}
        </Link>
      </div>
    </div>
  );
}

function analysisErrorText(err: unknown, t: TFunction): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return `${t("assistant.errors.rateLimit")} ${err.message}`.trim();
    if (err.status === 503) return `${t("assistant.errors.unavailable")} ${err.message}`.trim();
    return uploadErrorText(err, t);
  }
  return errorMessage(err);
}
