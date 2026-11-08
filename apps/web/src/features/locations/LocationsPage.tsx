import clsx from "clsx";
import {
  Archive,
  ArchiveRestore,
  ChevronDown,
  Camera,
  ChevronRight,
  Edit3,
  FolderInput,
  FolderPlus,
  Package,
  Plus,
  Printer,
  Trash2,
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api_, useApiMutation, useItems, useLocations } from "../../api/hooks";
import type { Location, LocationKind } from "../../api/types";
import { LocationSelect } from "../../components/Pickers";
import { Thumb } from "../../components/Thumb";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  Field,
  Input,
  Modal,
  Select,
  Spinner,
  Textarea,
  errorMessage,
  useToast,
} from "../../components/ui";
import {
  LOCATION_KINDS,
  type TreeNode,
  buildTree,
  formatQty,
  placementSummary,
  subtreeIds,
} from "../../lib/format";
import { useAuth } from "../auth/AuthProvider";
import FileGallery from "../files/FileGallery";
import PrintLabelsDialog from "../labels/PrintLabelsDialog";

const KINDS = LOCATION_KINDS;

/** Sdílený stav přetahování ve stromu umístění. */
interface DragCtx {
  dragId: string | null;
  /** umístění, na které nelze pustit (přetahované a jeho podstrom) */
  blocked: Set<string> | null;
  /** poslední přesun: větev `id` se má rozbalit (`n` odliší opakované přesuny do téhož místa) */
  reveal: { id: string | null; n: number };
  start: (id: string) => void;
  end: () => void;
  drop: (parentId: string | null) => void;
}

export default function LocationsPage() {
  const { t } = useTranslation();
  const toast = useToast();
  const { id } = useParams();
  const { can } = useAuth();
  const canWrite = can("items:write");
  const [showArchived, setShowArchived] = useState(false);
  const { data, isPending } = useLocations(showArchived);
  const [form, setForm] = useState<null | { edit?: Location; parent?: string | null }>(null);
  const tree = useMemo(() => buildTree(data ?? []), [data]);
  const selected = data?.find((l) => l.id === id);

  const [dragId, setDragId] = useState<string | null>(null);
  const [reveal, setReveal] = useState<DragCtx["reveal"]>({ id: null, n: 0 });
  const [moveError, setMoveError] = useState<string | null>(null);
  const blocked = useMemo(() => (dragId && data ? subtreeIds(data, dragId) : null), [data, dragId]);
  const move = useApiMutation(({ loc, parentId }: { loc: Location; parentId: string | null }) =>
    api_.updateLocation(loc.id, { parent_id: parentId, version: loc.version }),
  );
  const drag: DragCtx = {
    dragId,
    blocked,
    reveal,
    start: setDragId,
    end: () => setDragId(null),
    drop: (parentId) => {
      const loc = data?.find((l) => l.id === dragId);
      setDragId(null);
      if (!loc || loc.parent_id === parentId) return;
      setMoveError(null);
      move
        .mutateAsync({ loc, parentId })
        .then(() => {
          setReveal((r) => ({ id: parentId, n: r.n + 1 }));
          toast(t("locations.moved"));
        })
        .catch((e: unknown) => setMoveError(errorMessage(e)));
    },
  };

  return (
    <div className="mx-auto flex h-full max-w-7xl flex-col gap-3 p-3 md:flex-row md:p-5">
      <div className={clsx("min-w-0 md:w-96 md:shrink-0", id && "hidden md:block")}>
        <div className="mb-3 flex items-center gap-2">
          <h1 className="mr-auto text-xl font-bold">{t("nav.locations")}</h1>
          {can("items:write") && (
            <Button variant="primary" size="sm" onClick={() => setForm({ parent: null })}>
              <Plus className="size-4" /> {t("locations.add")}
            </Button>
          )}
        </div>
        <Card className="!p-2">
          {isPending ? (
            <Spinner />
          ) : tree.length === 0 ? (
            <EmptyState title={t("locations.empty")} hint={t("locations.emptyHint")} />
          ) : (
            <>
              {canWrite && dragId && (
                <RootDropZone
                  disabled={data?.find((l) => l.id === dragId)?.parent_id == null}
                  onDrop={() => drag.drop(null)}
                />
              )}
              <ul role="tree">
                {tree.map((n) => (
                  <TreeRow
                    key={n.node.id}
                    n={n}
                    depth={0}
                    selectedId={id}
                    drag={canWrite ? drag : null}
                  />
                ))}
              </ul>
            </>
          )}
        </Card>
        {moveError && (
          <p role="alert" className="mt-2 px-1 text-sm text-red-600">
            {moveError}
          </p>
        )}
        {canWrite && !dragId && tree.length > 0 && (
          <p className="mt-2 hidden px-1 text-xs text-slate-500 md:block">
            {t("locations.dragHint")}
          </p>
        )}
        <div className="mt-2 px-1">
          <Checkbox
            label={t("locations.showArchived")}
            checked={showArchived}
            onChange={setShowArchived}
          />
        </div>
      </div>

      <div className={clsx("min-w-0 flex-1", !id && "hidden md:block")}>
        {selected ? (
          <LocationDetail
            key={selected.id}
            loc={selected}
            onAddChild={() => setForm({ parent: selected.id })}
            onEdit={() => setForm({ edit: selected })}
          />
        ) : (
          <Card className="hidden md:block">
            <EmptyState title={t("locations.pickOne")} />
          </Card>
        )}
      </div>

      {form && <LocationFormModal {...form} onClose={() => setForm(null)} />}
    </div>
  );
}

function RootDropZone({ disabled, onDrop }: { disabled: boolean; onDrop: () => void }) {
  const { t } = useTranslation();
  const [over, setOver] = useState(false);
  return (
    <div
      onDragOver={(e) => {
        if (disabled) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!disabled) onDrop();
      }}
      className={clsx(
        "mb-1 rounded-lg border-2 border-dashed px-3 py-2 text-center text-xs",
        disabled && "opacity-40",
        over
          ? "border-brand-600 bg-brand-50 text-brand-700 dark:bg-brand-700/20"
          : "border-slate-300 text-slate-500 dark:border-slate-700",
      )}
    >
      {t("locations.dropRoot")}
    </div>
  );
}

function TreeRow({
  n,
  depth,
  selectedId,
  drag,
}: {
  n: TreeNode<Location>;
  depth: number;
  selectedId?: string;
  /** null = přetahování vypnuto (bez práva zápisu) */
  drag: DragCtx | null;
}) {
  const [open, setOpen] = useState(depth < 1);
  const [over, setOver] = useState(false);
  const expandTimer = useRef<number | undefined>(undefined);
  const loc = n.node;
  const has = n.children.length > 0;
  // Po přesunu se cílová větev rozbalí (stav se upravuje při renderu, ne v efektu).
  const [seenReveal, setSeenReveal] = useState(0);
  const reveal = drag?.reveal;
  if (reveal && reveal.id === loc.id && reveal.n !== seenReveal) {
    setSeenReveal(reveal.n);
    setOpen(true);
  }
  useEffect(() => () => window.clearTimeout(expandTimer.current), []);

  const canDropHere = !!drag?.dragId && !drag.blocked?.has(loc.id) && !loc.archived_at;
  const leave = () => {
    setOver(false);
    window.clearTimeout(expandTimer.current);
  };
  return (
    <li
      role="treeitem"
      aria-expanded={has ? open : undefined}
      aria-selected={selectedId === loc.id}
    >
      <div
        draggable={!!drag}
        onDragStart={(e) => {
          if (!drag) return;
          e.dataTransfer.setData("text/plain", loc.id);
          e.dataTransfer.effectAllowed = "move";
          drag.start(loc.id);
        }}
        onDragEnd={() => {
          leave();
          drag?.end();
        }}
        onDragOver={(e) => {
          if (!canDropHere) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
          if (!over) {
            setOver(true);
            // sbalená větev se po chvíli sama rozbalí, ať jde pustit i do podřízeného
            if (has && !open) {
              expandTimer.current = window.setTimeout(() => setOpen(true), 600);
            }
          }
        }}
        onDragLeave={leave}
        onDrop={(e) => {
          if (!canDropHere) return;
          e.preventDefault();
          leave();
          drag?.drop(loc.id);
        }}
        className={clsx(
          "flex items-center gap-1 rounded-lg pr-2",
          drag && "md:cursor-grab",
          drag?.dragId === loc.id && "opacity-40",
          over
            ? "bg-brand-100 ring-2 ring-brand-600 dark:bg-brand-700/30"
            : selectedId === loc.id
              ? "bg-brand-50 dark:bg-brand-700/20"
              : "hover:bg-slate-100 dark:hover:bg-slate-800",
        )}
        style={{ paddingLeft: depth * 14 }}
      >
        <button
          className="grid size-7 place-items-center text-slate-400"
          aria-label={open ? "Sbalit" : "Rozbalit"}
          onClick={() => setOpen((o) => !o)}
          disabled={!has}
        >
          {has ? (
            open ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )
          ) : (
            <span className="size-1 rounded-full bg-slate-300" />
          )}
        </button>
        <Link
          to={`/locations/${loc.id}`}
          draggable={false}
          className="flex min-w-0 flex-1 items-center gap-2 py-1.5 text-sm"
        >
          <span className={clsx("truncate", loc.archived_at && "text-slate-400 line-through")}>
            {loc.name}
          </span>
          {loc.is_movable && <Badge>box</Badge>}
          <span className="ml-auto text-xs text-slate-400">{loc.item_count}</span>
        </Link>
      </div>
      {has && open && (
        <ul role="group">
          {n.children.map((c) => (
            <TreeRow key={c.node.id} n={c} depth={depth + 1} selectedId={selectedId} drag={drag} />
          ))}
        </ul>
      )}
    </li>
  );
}

function LocationDetail({
  loc,
  onAddChild,
  onEdit,
}: {
  loc: Location;
  onAddChild: () => void;
  onEdit: () => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const { can } = useAuth();
  const canWrite = can("items:write");
  const items = useItems({ location_id: loc.id, limit: 200, sort: "name" });
  const { data: allLocations } = useLocations(true);
  const [error, setError] = useState<string | null>(null);
  const [printing, setPrinting] = useState(false);
  const [moving, setMoving] = useState(false);
  const childIds = useMemo(() => descendantIds(allLocations ?? [], loc.id), [allLocations, loc.id]);

  const archive = useApiMutation(() =>
    loc.archived_at ? api_.unarchiveLocation(loc.id) : api_.archiveLocation(loc.id),
  );
  const remove = useApiMutation(() => api_.deleteLocation(loc.id), {
    onSuccess: () => {
      toast(t("common.done"));
      navigate("/locations");
    },
  });
  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <div className="space-y-3">
      <Card className="space-y-3">
        <Link to="/locations" className="text-sm text-brand-700 md:hidden dark:text-brand-100">
          ← {t("nav.locations")}
        </Link>
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-bold">{loc.name}</h2>
            <Badge>{t(`kind.${loc.kind}`)}</Badge>
            {loc.archived_at && <Badge tone="red">{t("locations.archived")}</Badge>}
            <span className="font-mono text-xs text-slate-500">{loc.label_code}</span>
          </div>
          <p className="text-sm text-slate-500">{loc.full_name}</p>
        </div>
        {loc.description && <p className="text-sm">{loc.description}</p>}
        {loc.notes && (
          <p className="rounded-lg bg-amber-50 p-3 text-sm dark:bg-amber-950/40">{loc.notes}</p>
        )}
        <p className="text-sm text-slate-500">
          {t("locations.itemCount", { count: loc.item_count, direct: loc.direct_item_count })}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setPrinting(true)}>
            <Printer className="size-4" /> {t("labels.printOne")}
          </Button>
        </div>
        {canWrite && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={onEdit}>
              <Edit3 className="size-4" /> {t("common.edit")}
            </Button>
            <Button size="sm" onClick={() => setMoving(true)}>
              <FolderInput className="size-4" /> {t("locations.move")}
            </Button>
            <Button size="sm" onClick={onAddChild}>
              <FolderPlus className="size-4" /> {t("locations.addChild")}
            </Button>
            <Button size="sm" onClick={() => navigate(`/items?location_id=${loc.id}&new=1`)}>
              <Plus className="size-4" /> {t("locations.addItem")}
            </Button>
            <Button size="sm" onClick={() => navigate(`/add-photo?location_id=${loc.id}`)}>
              <Camera className="size-4" /> {t("locations.addFromPhoto")}
            </Button>
            <Button size="sm" onClick={() => run(() => archive.mutateAsync(undefined))}>
              {loc.archived_at ? (
                <ArchiveRestore className="size-4" />
              ) : (
                <Archive className="size-4" />
              )}
              {loc.archived_at ? t("locations.unarchive") : t("locations.archive")}
            </Button>
            <Button size="sm" onClick={() => run(() => remove.mutateAsync(undefined))}>
              <Trash2 className="size-4" /> {t("common.delete")}
            </Button>
          </div>
        )}
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
      </Card>

      <Card>
        <FileGallery kind="location" id={loc.id} canWrite={canWrite} />
      </Card>

      <Card className="!p-0">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <h3 className="flex items-center gap-2 font-semibold">
            <Package className="size-4" /> {t("locations.contents")}
          </h3>
          <Link
            to={`/items?location_id=${loc.id}`}
            className="text-sm text-brand-700 dark:text-brand-100"
          >
            {t("locations.openInItems")}
          </Link>
        </div>
        {items.isPending ? (
          <Spinner />
        ) : items.data?.items.length ? (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {items.data.items.map((i) => (
              <li key={i.id}>
                <Link
                  to={`/items/${i.id}`}
                  className="flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50"
                >
                  <Thumb fileId={i.primary_file_id} className="size-10" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{i.name}</span>
                    <span className="block truncate text-xs text-slate-500">
                      {placementSummary(i)}
                    </span>
                  </span>
                  <span className="text-slate-500">{formatQty(i.total_quantity, i.unit)}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="p-4 text-sm text-slate-500">{t("locations.emptyContents")}</p>
        )}
      </Card>
      {moving && <MoveLocationModal loc={loc} onClose={() => setMoving(false)} />}
      <PrintLabelsDialog
        open={printing}
        onClose={() => setPrinting(false)}
        kind="location"
        ids={[loc.id]}
        extraIds={childIds}
        extraLabel={t("labels.includeChildren", { count: childIds.length })}
      />
    </div>
  );
}

/** Přesun umístění výběrem nového nadřazeného (náhrada přetahování na dotykových zařízeních). */
function MoveLocationModal({ loc, onClose }: { loc: Location; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [parentId, setParentId] = useState<string | null>(loc.parent_id);
  const [error, setError] = useState<string | null>(null);
  const save = useApiMutation(
    () => api_.updateLocation(loc.id, { parent_id: parentId, version: loc.version }),
    {
      onSuccess: () => {
        toast(t("locations.moved"));
        onClose();
      },
    },
  );
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await save.mutateAsync(undefined);
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  return (
    <Modal open onClose={onClose} title={t("locations.moveTitle", { name: loc.name })}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t("locations.moveTo")}>
          {(id) => (
            <LocationSelect
              id={id}
              value={parentId}
              onChange={setParentId}
              exclude={loc.id}
              emptyLabel={t("locations.root")}
            />
          )}
        </Field>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            type="submit"
            variant="primary"
            disabled={save.isPending || parentId === loc.parent_id}
          >
            {t("locations.move")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/** ID všech podřízených umístění (v pořadí průchodu stromem). */
function descendantIds(all: Location[], rootId: string): string[] {
  const out: string[] = [];
  const known = new Set([rootId]);
  for (const l of all) {
    if (l.parent_id && known.has(l.parent_id)) {
      known.add(l.id);
      out.push(l.id);
    }
  }
  return out;
}

function LocationFormModal({
  edit,
  parent,
  onClose,
}: {
  edit?: Location;
  parent?: string | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const [name, setName] = useState(edit?.name ?? "");
  const [kind, setKind] = useState<LocationKind>(edit?.kind ?? "other");
  const [parentId, setParentId] = useState<string | null>(edit ? edit.parent_id : (parent ?? null));
  const [movable, setMovable] = useState(edit?.is_movable ?? false);
  const [description, setDescription] = useState(edit?.description ?? "");
  const [notes, setNotes] = useState(edit?.notes ?? "");
  const [error, setError] = useState<string | null>(null);

  const save = useApiMutation(
    () => {
      const body = {
        name: name.trim(),
        kind,
        parent_id: parentId,
        is_movable: movable,
        description: description.trim() || null,
        notes: notes.trim() || null,
      };
      return edit
        ? api_.updateLocation(edit.id, { ...body, version: edit.version })
        : api_.createLocation(body);
    },
    {
      onSuccess: (saved) => {
        toast(t("common.saved"));
        onClose();
        if (!edit) navigate(`/locations/${(saved as Location).id}`);
      },
    },
  );

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await save.mutateAsync(undefined);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal open onClose={onClose} title={edit ? t("locations.edit") : t("locations.add")}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t("locations.name")}>
          {(id) => (
            <Input
              id={id}
              autoFocus
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          )}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("locations.kindLabel")}>
            {(id) => (
              <Select
                id={id}
                value={kind}
                onChange={(e) => setKind(e.target.value as LocationKind)}
              >
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {t(`kind.${k}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t("locations.parent")}>
            {(id) => (
              <LocationSelect
                id={id}
                value={parentId}
                onChange={setParentId}
                exclude={edit?.id}
                emptyLabel={t("locations.root")}
              />
            )}
          </Field>
        </div>
        <Checkbox label={t("locations.movable")} checked={movable} onChange={setMovable} />
        <Field label={t("items.description")}>
          {(id) => (
            <Textarea
              id={id}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("items.notes")}>
          {(id) => <Textarea id={id} value={notes} onChange={(e) => setNotes(e.target.value)} />}
        </Field>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button type="submit" variant="primary" disabled={save.isPending || !name.trim()}>
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
