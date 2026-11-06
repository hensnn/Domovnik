import {
  AlertTriangle,
  Camera,
  ClipboardCheck,
  FolderTree,
  HelpCircle,
  Package,
  ScanLine,
  ShieldAlert,
  Sparkles,
  Tags,
  Timer,
  Trash2,
} from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useDashboard, useLocations } from "../../api/hooks";
import type { Item } from "../../api/types";
import { Card, EmptyState, Spinner, errorMessage } from "../../components/ui";
import { formatDate, formatDateTime, formatQty } from "../../lib/format";
import { useAuth } from "../auth/AuthProvider";

export default function DashboardPage() {
  const { t } = useTranslation();
  const { me, can } = useAuth();
  const { data, isPending, isError, error } = useDashboard();
  const { data: locs = [] } = useLocations(true);
  if (isPending) return <Spinner />;
  if (isError)
    return (
      <p role="alert" className="p-4 text-red-600">
        {errorMessage(error)}
      </p>
    );
  const c = data.counts;
  const name = (id: string | null) => locs.find((l) => l.id === id)?.full_name ?? "–";

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-3 md:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-xl font-bold">
          {t("dashboard.hello", { name: me.user.display_name })}
        </h1>
        {can("items:write") && (
          <Link
            to="/add-photo"
            className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            <Camera className="size-4" /> {t("nav.addPhoto")}
          </Link>
        )}
        <Link
          to="/assistant"
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-sm font-medium hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800"
        >
          <Sparkles className="size-4" /> {t("nav.assistant")}
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Link
          to="/scan"
          className="flex items-center gap-3 rounded-xl bg-brand-600 p-4 font-semibold text-white hover:bg-brand-700"
        >
          <ScanLine className="size-6" /> {t("scan.title")}
        </Link>
        <Link
          to="/inventory"
          className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 font-semibold hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:bg-slate-800"
        >
          <ClipboardCheck className="size-6 text-brand-600" /> {t("inventory.nav")}
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat to="/items" icon={<Package />} label={t("dashboard.items")} value={c.items} />
        <Stat
          to="/locations"
          icon={<FolderTree />}
          label={t("dashboard.locations")}
          value={c.locations}
        />
        <Stat
          to="/categories"
          icon={<Tags />}
          label={t("dashboard.categories")}
          value={c.categories}
        />
        <Stat to="/items?trash=1" icon={<Trash2 />} label={t("dashboard.trash")} value={c.trash} />
      </div>

      {(c.unplaced > 0 || c.uncategorized > 0) && (
        <div className="grid gap-3 md:grid-cols-2">
          {c.unplaced > 0 && (
            <Alert to="/items?unplaced=1" tone="amber" icon={<HelpCircle className="size-5" />}>
              {t("dashboard.unplaced", { count: c.unplaced })}
            </Alert>
          )}
          {c.uncategorized > 0 && (
            <Alert to="/items?sort=name" tone="blue" icon={<Tags className="size-5" />}>
              {t("dashboard.uncategorized", { count: c.uncategorized })}
            </Alert>
          )}
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        <ListCard
          title={t("dashboard.lowStock")}
          icon={<AlertTriangle className="size-4 text-amber-600" />}
          items={data.low_stock}
          more={c.low_stock > data.low_stock.length ? "/items?low_stock=1" : undefined}
          meta={(i) => formatQty(i.total_quantity, i.unit)}
        />
        <ListCard
          title={t("dashboard.warranty")}
          icon={<ShieldAlert className="size-4 text-sky-600" />}
          items={data.warranty_soon}
          meta={(i) => formatDate(i.warranty_until)}
        />
        <ListCard
          title={t("dashboard.expiring")}
          icon={<Timer className="size-4 text-red-600" />}
          items={data.expiring_soon}
          meta={(i) => formatDate(i.expires_at)}
        />
        <Card className="!p-0">
          <h2 className="border-b border-slate-200 px-4 py-3 font-semibold dark:border-slate-800">
            {t("dashboard.recent")}
          </h2>
          {data.recent_movements.length === 0 ? (
            <EmptyState title={t("dashboard.noMovements")} />
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {data.recent_movements.map((m) => (
                <li key={m.id}>
                  <Link
                    to={`/items/${m.item_id}`}
                    className="block px-4 py-2.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50"
                  >
                    <div className="flex justify-between gap-2">
                      <span className="font-medium">{t(`movement.${m.kind}`)}</span>
                      <span className="text-xs text-slate-500">{formatDateTime(m.moved_at)}</span>
                    </div>
                    <div className="truncate text-xs text-slate-500">
                      {m.from_location_id && `${name(m.from_location_id)} → `}
                      {m.to_location_id ? name(m.to_location_id) : ""}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function Stat({
  to,
  icon,
  label,
  value,
}: {
  to: string;
  icon: ReactNode;
  label: string;
  value: number;
}) {
  return (
    <Link
      to={to}
      className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 hover:border-brand-500 dark:border-slate-800 dark:bg-slate-900"
    >
      <span className="text-brand-600 [&>svg]:size-6">{icon}</span>
      <span>
        <span className="block text-2xl font-bold leading-none">{value}</span>
        <span className="text-xs text-slate-500">{label}</span>
      </span>
    </Link>
  );
}

function Alert({
  to,
  tone,
  icon,
  children,
}: {
  to: string;
  tone: "amber" | "blue";
  icon: ReactNode;
  children: ReactNode;
}) {
  const cls =
    tone === "amber"
      ? "bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
      : "bg-sky-50 text-sky-900 dark:bg-sky-950/40 dark:text-sky-200";
  return (
    <Link to={to} className={`flex items-center gap-3 rounded-xl p-4 text-sm font-medium ${cls}`}>
      {icon}
      {children}
    </Link>
  );
}

function ListCard({
  title,
  icon,
  items,
  meta,
  more,
}: {
  title: string;
  icon: ReactNode;
  items: Item[];
  meta: (i: Item) => string;
  more?: string;
}) {
  const { t } = useTranslation();
  return (
    <Card className="!p-0">
      <h2 className="flex items-center gap-2 border-b border-slate-200 px-4 py-3 font-semibold dark:border-slate-800">
        {icon} {title}
      </h2>
      {items.length === 0 ? (
        <p className="p-4 text-sm text-slate-500">{t("dashboard.nothing")}</p>
      ) : (
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {items.map((i) => (
            <li key={i.id}>
              <Link
                to={`/items/${i.id}`}
                className="flex justify-between gap-2 px-4 py-2.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50"
              >
                <span className="truncate">{i.name}</span>
                <span className="shrink-0 text-slate-500">{meta(i)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {more && (
        <Link
          to={more}
          className="block border-t border-slate-200 px-4 py-2 text-sm text-brand-700 dark:border-slate-800 dark:text-brand-100"
        >
          {t("dashboard.showAll")}
        </Link>
      )}
    </Card>
  );
}
