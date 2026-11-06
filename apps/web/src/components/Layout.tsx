import clsx from "clsx";
import {
  Boxes,
  Camera,
  ClipboardCheck,
  FolderTree,
  LayoutDashboard,
  LogOut,
  MoreHorizontal,
  Package,
  ScanLine,
  Search,
  Settings as SettingsIcon,
  Sparkles,
  Tags,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../features/auth/AuthProvider";
import CommandPalette from "./CommandPalette";
import CurrentLocationChip from "./CurrentLocationChip";
import OfflineBanner from "./OfflineBanner";
import { IconButton, Modal } from "./ui";
import { useLiveUpdates } from "./useLiveUpdates";
import { useThemeSetting } from "./useTheme";

const NAV = [
  { to: "/", key: "nav.dashboard", icon: LayoutDashboard, end: true },
  { to: "/items", key: "nav.items", icon: Package },
  { to: "/assistant", key: "nav.assistant", icon: Sparkles },
  { to: "/locations", key: "nav.locations", icon: FolderTree },
  { to: "/categories", key: "nav.categories", icon: Tags },
  { to: "/settings", key: "nav.settings", icon: SettingsIcon },
] as const;

/** Spodní navigace na mobilu: hlavní cíle + „Přidat“ uprostřed; zbytek schovává „Více“. */
const MOBILE_MAIN = [NAV[0], NAV[1]] as const;
const MOBILE_AFTER = [NAV[2]] as const;
const MOBILE_MORE = [NAV[3], NAV[4], NAV[5]] as const;
/** Další položky jen v postranním menu na desktopu (na mobilu: tlačítko Skenovat v hlavičce a přehled). */
const EXTRA_NAV = [
  { to: "/scan", key: "scan.nav", icon: ScanLine },
  { to: "/inventory", key: "inventory.nav", icon: ClipboardCheck },
] as const;

export default function Layout() {
  const { t } = useTranslation();
  const { me, logout, can } = useAuth();
  const canWrite = can("items:write");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  useLiveUpdates();
  useThemeSetting();

  return (
    <div className="flex h-full flex-col md:flex-row">
      {/* Postranní navigace (desktop) */}
      <aside className="hidden w-56 shrink-0 flex-col border-r border-slate-200 bg-white md:flex dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-2 px-4 py-4 text-lg font-bold text-brand-600">
          <Boxes className="size-6" /> {t("app.name")}
        </div>
        {canWrite && (
          <div className="px-2 pb-2">
            <NavLink
              to="/add-photo"
              className="flex items-center justify-center gap-2 rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700"
            >
              <Camera className="size-5" /> {t("nav.addPhoto")}
            </NavLink>
          </div>
        )}
        <nav className="flex-1 space-y-1 px-2">
          {NAV.map(({ to, key, icon: Icon, ...rest }) => (
            <NavLink
              key={to}
              to={to}
              end={"end" in rest}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
                  isActive
                    ? "bg-brand-50 text-brand-700 dark:bg-brand-700/20 dark:text-brand-100"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
                )
              }
            >
              <Icon className="size-5" /> {t(key)}
            </NavLink>
          ))}
          {EXTRA_NAV.map(({ to, key, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
                  isActive
                    ? "bg-brand-50 text-brand-700 dark:bg-brand-700/20 dark:text-brand-100"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
                )
              }
            >
              <Icon className="size-5" /> {t(key)}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-200 p-3 text-sm dark:border-slate-800">
          <div className="truncate font-medium">{me.user.display_name}</div>
          <div className="mb-2 text-xs text-slate-500">{t(`roles.${me.user.role}`)}</div>
          <button
            onClick={() => void logout()}
            className="flex items-center gap-2 text-slate-500 hover:text-slate-900 dark:hover:text-slate-100"
          >
            <LogOut className="size-4" /> {t("auth.logout")}
          </button>
        </div>
      </aside>

      <div className="flex min-h-0 flex-1 flex-col">
        <OfflineBanner />
        <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
          <span className="flex items-center gap-1 font-bold text-brand-600 md:hidden">
            <Boxes className="size-5" />
          </span>
          <button
            onClick={() => setPaletteOpen(true)}
            className="flex flex-1 items-center gap-2 rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 text-left text-sm text-slate-500 hover:bg-white md:max-w-md dark:border-slate-700 dark:bg-slate-800"
            aria-label={t("search.open")}
          >
            <Search className="size-4" />
            <span className="flex-1">{t("search.placeholder")}</span>
            <kbd className="hidden rounded border border-slate-300 px-1.5 text-xs md:inline dark:border-slate-600">
              Ctrl K
            </kbd>
          </button>
          <Link
            to="/scan"
            aria-label={t("scan.title")}
            title={t("scan.title")}
            className="grid size-10 shrink-0 place-items-center rounded-lg text-slate-700 hover:bg-slate-200/70 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <ScanLine className="size-5" />
          </Link>
          <div className="order-last basis-full md:order-none md:basis-auto">
            <CurrentLocationChip />
          </div>
          <IconButton label={t("auth.logout")} className="md:hidden" onClick={() => void logout()}>
            <LogOut className="size-5" />
          </IconButton>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>

        {/* Spodní navigace (mobil) */}
        <nav
          aria-label={t("nav.mobile")}
          className="pb-safe grid grid-cols-5 border-t border-slate-200 bg-white md:hidden dark:border-slate-800 dark:bg-slate-900"
        >
          {MOBILE_MAIN.map((n) => (
            <MobileLink key={n.to} item={n} />
          ))}
          {canWrite ? (
            <NavLink
              to="/add-photo"
              aria-label={t("nav.addPhoto")}
              className="flex flex-col items-center gap-0.5 py-1 text-[11px] font-medium text-brand-600"
            >
              <span className="-mt-4 flex size-11 items-center justify-center rounded-full bg-brand-600 text-white shadow-md">
                <Camera className="size-6" />
              </span>
              {t("nav.addShort")}
            </NavLink>
          ) : (
            <span />
          )}
          {MOBILE_AFTER.map((n) => (
            <MobileLink key={n.to} item={n} />
          ))}
          <button
            onClick={() => setMoreOpen(true)}
            className="flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium text-slate-500"
          >
            <MoreHorizontal className="size-5" />
            {t("nav.more")}
          </button>
        </nav>
      </div>

      <Modal open={moreOpen} onClose={() => setMoreOpen(false)} title={t("nav.more")}>
        <ul className="space-y-1">
          {MOBILE_MORE.map(({ to, key, icon: Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                onClick={() => setMoreOpen(false)}
                className="flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <Icon className="size-5" /> {t(key)}
              </NavLink>
            </li>
          ))}
        </ul>
      </Modal>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}

function MobileLink({ item }: { item: (typeof NAV)[number] }) {
  const { t } = useTranslation();
  const { to, key, icon: Icon } = item;
  return (
    <NavLink
      to={to}
      end={"end" in item}
      className={({ isActive }) =>
        clsx(
          "flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium",
          isActive ? "text-brand-600" : "text-slate-500",
        )
      }
    >
      <Icon className="size-5" />
      {t(`${key}Short`)}
    </NavLink>
  );
}
