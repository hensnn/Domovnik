import clsx from "clsx";
import { RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { api_, useApiMutation, useSettings, useTokens, useUsers } from "../../api/hooks";
import type { SettingDef } from "../../api/types";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Field,
  Input,
  Modal,
  Select,
  Spinner,
  Textarea,
  errorMessage,
  useToast,
} from "../../components/ui";
import { formatDateTime } from "../../lib/format";
import { useAuth } from "../auth/AuthProvider";

type Tab = string; // skupina nastavení | "account" | "users"

export default function SettingsPage() {
  const { t } = useTranslation();
  const { isAdmin } = useAuth();
  const { data, isPending } = useSettings();
  const [searchParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>(searchParams.get("tab") ?? "ui");

  const groups = useMemo(() => {
    const map = new Map<string, string>();
    data?.forEach((s) => map.set(s.group, s.group_label));
    return [...map.entries()];
  }, [data]);

  if (isPending) return <Spinner />;

  const tabs: [string, string][] = [
    ["account", t("settings.account")],
    ...groups,
    ...(isAdmin ? ([["users", t("settings.users")]] as [string, string][]) : []),
  ];

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-3 p-3 md:flex-row md:p-5">
      <nav
        className="flex gap-1 overflow-x-auto md:w-52 md:shrink-0 md:flex-col"
        aria-label={t("nav.settings")}
      >
        {tabs.map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            aria-current={tab === key}
            className={clsx(
              "whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm font-medium",
              tab === key
                ? "bg-brand-50 text-brand-700 dark:bg-brand-700/20 dark:text-brand-100"
                : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
            )}
          >
            {label}
          </button>
        ))}
      </nav>
      <div className="min-w-0 flex-1 space-y-3">
        {tab === "account" ? (
          <AccountTab />
        ) : tab === "users" ? (
          <UsersTab />
        ) : (
          <GroupTab group={tab} defs={data!.filter((s) => s.group === tab)} />
        )}
      </div>
    </div>
  );
}

function GroupTab({ group, defs }: { group: string; defs: SettingDef[] }) {
  const title = defs[0]?.group_label ?? group;
  return (
    <Card className="divide-y divide-slate-100 !p-0 dark:divide-slate-800">
      <h1 className="px-4 py-3 text-lg font-bold">{title}</h1>
      {defs.map((d) => (
        <SettingRow key={`${d.key}:${JSON.stringify(d.value)}`} def={d} />
      ))}
    </Card>
  );
}

function SettingRow({ def }: { def: SettingDef }) {
  const { t } = useTranslation();
  const toast = useToast();
  const { isAdmin } = useAuth();
  // Kam se ukládá: uživatelské nastavení = jen pro mě; ostatní globálně (jen admin)
  const scope: "user" | "global" = def.scope === "user" ? "user" : "global";
  const locked = scope === "global" && !isAdmin;
  const [draft, setDraft] = useState<unknown>(def.type === "secret" ? "" : def.value);
  const [error, setError] = useState<string | null>(null);

  const save = useApiMutation((value: unknown) => api_.putSetting(def.key, value, scope), {
    invalidate: false,
    onSuccess: () => toast(t("settings.saved", { name: def.label })),
  });
  const reset = useApiMutation(() => api_.resetSetting(def.key, scope), { invalidate: false });
  const qc = useSettingsInvalidate();

  async function commit(value: unknown) {
    setError(null);
    try {
      await save.mutateAsync(value);
      qc();
    } catch (e) {
      setError(errorMessage(e));
      setDraft(def.type === "secret" ? "" : def.value);
    }
  }

  const input = (() => {
    switch (def.type) {
      case "bool":
        return (
          <Checkbox
            label={draft ? t("common.yes") : t("common.no")}
            checked={draft === true}
            disabled={locked}
            onChange={(v) => {
              setDraft(v);
              void commit(v);
            }}
          />
        );
      case "enum":
        return (
          <Select
            aria-label={def.label}
            value={String(draft)}
            disabled={locked}
            onChange={(e) => {
              setDraft(e.target.value);
              void commit(e.target.value);
            }}
          >
            {def.choices.map((c) => (
              <option key={c} value={c}>
                {c === "\t" ? "TAB" : c}
              </option>
            ))}
          </Select>
        );
      case "int":
      case "float":
        return (
          <Input
            aria-label={def.label}
            type="number"
            step={def.type === "int" ? 1 : "any"}
            min={def.min ?? undefined}
            max={def.max ?? undefined}
            value={String(draft ?? "")}
            disabled={locked}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => {
              const n = Number(draft);
              if (draft !== "" && n !== def.value)
                void commit(def.type === "int" ? Math.round(n) : n);
            }}
          />
        );
      case "text":
        return (
          <Textarea
            aria-label={def.label}
            value={String(draft ?? "")}
            disabled={locked}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => draft !== def.value && void commit(draft)}
          />
        );
      case "string_list":
        return (
          <Input
            aria-label={def.label}
            value={(draft as string[]).join(", ")}
            disabled={locked}
            placeholder="a, b, c"
            onChange={(e) =>
              setDraft(
                e.target.value
                  .split(",")
                  .map((x) => x.trim())
                  .filter(Boolean),
              )
            }
            onBlur={() => void commit(draft)}
          />
        );
      case "secret":
        return (
          <Input
            aria-label={def.label}
            type="password"
            autoComplete="off"
            disabled={locked}
            placeholder={def.has_value ? t("settings.secretSet") : t("settings.secretEmpty")}
            value={String(draft ?? "")}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => {
              if (draft) void commit(draft);
            }}
          />
        );
      default:
        return (
          <Input
            aria-label={def.label}
            value={String(draft ?? "")}
            disabled={locked}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => draft !== def.value && void commit(draft)}
          />
        );
    }
  })();

  return (
    <div className="grid gap-2 px-4 py-3 md:grid-cols-[1fr_16rem] md:items-start">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{def.label}</span>
          {def.scope === "user" && <Badge tone="blue">{t("settings.perUser")}</Badge>}
          {def.restart_required && <Badge tone="amber">{t("settings.restart")}</Badge>}
          {locked && <Badge>{t("settings.adminOnly")}</Badge>}
        </div>
        {def.description && <p className="text-xs text-slate-500">{def.description}</p>}
        <p className="font-mono text-[11px] text-slate-400">{def.key}</p>
        {error && (
          <p role="alert" className="text-xs text-red-600">
            {error}
          </p>
        )}
      </div>
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">{input}</div>
        {!def.is_default && !locked && (
          <Button
            size="sm"
            variant="ghost"
            aria-label={t("settings.reset")}
            title={t("settings.reset")}
            onClick={async () => {
              await reset.mutateAsync(undefined);
              qc();
            }}
          >
            <RotateCcw className="size-4" />
          </Button>
        )}
      </div>
    </div>
  );
}

import { useQueryClient } from "@tanstack/react-query";
function useSettingsInvalidate() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: ["settings"] });
}

// --- Účet ---------------------------------------------------------------------------------

function AccountTab() {
  const { t } = useTranslation();
  const toast = useToast();
  const { me } = useAuth();
  const tokens = useTokens();
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const [tokenName, setTokenName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["items:read"]);

  const pw = useApiMutation(
    () => api_.changePassword({ old_password: oldPw, new_password: newPw }),
    {
      invalidate: false,
      onSuccess: () => {
        toast(t("settings.passwordChanged"));
        setOldPw("");
        setNewPw("");
        setTimeout(() => window.location.reload(), 800);
      },
    },
  );
  const create = useApiMutation(() => api_.createToken({ name: tokenName, scopes }), {
    invalidate: false,
    onSuccess: (r) => {
      setCreated((r as { token: string }).token);
      setTokenName("");
      void tokens.refetch();
    },
  });
  const revoke = useApiMutation((id: string) => api_.revokeToken(id), {
    invalidate: false,
    onSuccess: () => void tokens.refetch(),
  });
  const available = me.scopes.includes("admin")
    ? ["items:read", "items:write", "files:write", "ai:chat", "admin"]
    : me.scopes;

  return (
    <>
      <Card className="space-y-3">
        <h1 className="text-lg font-bold">{t("settings.account")}</h1>
        <p className="text-sm text-slate-500">
          {me.user.display_name} · {me.user.username} · {t(`roles.${me.user.role}`)}
        </p>
        <h2 className="pt-2 font-semibold">{t("settings.changePassword")}</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("settings.oldPassword")}>
            {(id) => (
              <Input
                id={id}
                type="password"
                autoComplete="current-password"
                value={oldPw}
                onChange={(e) => setOldPw(e.target.value)}
              />
            )}
          </Field>
          <Field label={t("settings.newPassword")} hint={t("auth.passwordHint")}>
            {(id) => (
              <Input
                id={id}
                type="password"
                autoComplete="new-password"
                value={newPw}
                onChange={(e) => setNewPw(e.target.value)}
              />
            )}
          </Field>
        </div>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <Button
          variant="primary"
          disabled={!oldPw || newPw.length < 10 || pw.isPending}
          onClick={async () => {
            setError(null);
            try {
              await pw.mutateAsync(undefined);
            } catch (e) {
              setError(errorMessage(e));
            }
          }}
        >
          {t("settings.changePassword")}
        </Button>
      </Card>

      <Card className="space-y-3">
        <h2 className="text-lg font-bold">{t("settings.tokens")}</h2>
        <p className="text-sm text-slate-500">{t("settings.tokensHint")}</p>
        {tokens.data?.length ? (
          <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
            {tokens.data.map((tk) => (
              <li key={tk.id} className="flex flex-wrap items-center gap-2 py-2">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">
                    {tk.name} {tk.revoked_at && <Badge tone="red">{t("settings.revoked")}</Badge>}
                  </div>
                  <div className="text-xs text-slate-500">
                    {tk.scopes.join(", ")} ·{" "}
                    {tk.last_used_at ? formatDateTime(tk.last_used_at) : t("settings.neverUsed")}
                  </div>
                </div>
                {!tk.revoked_at && (
                  <Button size="sm" onClick={() => revoke.mutate(tk.id)}>
                    {t("settings.revoke")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-500">{t("settings.noTokens")}</p>
        )}
        <div className="space-y-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
          <Field label={t("settings.tokenName")}>
            {(id) => (
              <Input
                id={id}
                value={tokenName}
                onChange={(e) => setTokenName(e.target.value)}
                placeholder="Home Assistant"
              />
            )}
          </Field>
          <div className="flex flex-wrap gap-3">
            {available.map((s) => (
              <Checkbox
                key={s}
                label={s}
                checked={scopes.includes(s)}
                onChange={(on) => setScopes(on ? [...scopes, s] : scopes.filter((x) => x !== s))}
              />
            ))}
          </div>
          <Button
            variant="primary"
            disabled={!tokenName.trim() || !scopes.length || create.isPending}
            onClick={() => create.mutate(undefined)}
          >
            {t("settings.createToken")}
          </Button>
        </div>
      </Card>

      <Modal
        open={!!created}
        onClose={() => setCreated(null)}
        title={t("settings.tokenCreated")}
        footer={
          <Button variant="primary" onClick={() => setCreated(null)}>
            {t("common.done")}
          </Button>
        }
      >
        <p className="mb-2 text-sm">{t("settings.tokenOnce")}</p>
        <code className="block break-all rounded-lg bg-slate-100 p-3 text-sm dark:bg-slate-800">
          {created}
        </code>
      </Modal>
    </>
  );
}

// --- Uživatelé (admin) --------------------------------------------------------------------

function UsersTab() {
  const { t } = useTranslation();
  const toast = useToast();
  const users = useUsers();
  const [open, setOpen] = useState(false);
  const patch = useApiMutation((v: { id: string; body: unknown }) => api_.patchUser(v.id, v.body), {
    invalidate: false,
    onSuccess: () => void users.refetch(),
  });
  return (
    <Card className="space-y-3">
      <div className="flex items-center">
        <h1 className="mr-auto text-lg font-bold">{t("settings.users")}</h1>
        <Button variant="primary" size="sm" onClick={() => setOpen(true)}>
          {t("settings.addUser")}
        </Button>
      </div>
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {users.data?.map((u) => (
          <li key={u.id} className="flex flex-wrap items-center gap-2 py-2.5 text-sm">
            <div className="min-w-0 flex-1">
              <div className="font-medium">
                {u.display_name}{" "}
                {!u.is_active && <Badge tone="red">{t("settings.inactive")}</Badge>}
              </div>
              <div className="text-xs text-slate-500">
                {u.username} ·{" "}
                {u.last_login_at ? formatDateTime(u.last_login_at) : t("settings.neverUsed")}
              </div>
            </div>
            <Select
              aria-label={t("settings.role")}
              className="!w-32"
              value={u.role}
              onChange={async (e) => {
                try {
                  await patch.mutateAsync({ id: u.id, body: { role: e.target.value } });
                } catch (err) {
                  toast(errorMessage(err), "error");
                }
              }}
            >
              {["admin", "member", "viewer", "guest"].map((r) => (
                <option key={r} value={r}>
                  {t(`roles.${r}`)}
                </option>
              ))}
            </Select>
            <Button
              size="sm"
              onClick={async () => {
                try {
                  await patch.mutateAsync({ id: u.id, body: { is_active: !u.is_active } });
                } catch (err) {
                  toast(errorMessage(err), "error");
                }
              }}
            >
              {u.is_active ? t("settings.deactivate") : t("settings.activate")}
            </Button>
          </li>
        ))}
      </ul>
      {open && (
        <AddUserModal
          onClose={() => {
            setOpen(false);
            void users.refetch();
          }}
        />
      )}
    </Card>
  );
}

function AddUserModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("member");
  const [error, setError] = useState<string | null>(null);
  const create = useApiMutation(
    () => api_.createUser({ username, display_name: displayName || username, password, role }),
    { invalidate: false, onSuccess: onClose },
  );
  return (
    <Modal
      open
      onClose={onClose}
      title={t("settings.addUser")}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            variant="primary"
            disabled={!username || password.length < 10 || create.isPending}
            onClick={async () => {
              setError(null);
              try {
                await create.mutateAsync(undefined);
              } catch (e) {
                setError(errorMessage(e));
              }
            }}
          >
            {t("common.create")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label={t("auth.username")}>
          {(id) => <Input id={id} value={username} onChange={(e) => setUsername(e.target.value)} />}
        </Field>
        <Field label={t("auth.displayName")}>
          {(id) => (
            <Input id={id} value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          )}
        </Field>
        <Field label={t("auth.password")} hint={t("auth.passwordHint")}>
          {(id) => (
            <Input
              id={id}
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("settings.role")}>
          {(id) => (
            <Select id={id} value={role} onChange={(e) => setRole(e.target.value)}>
              {["admin", "member", "viewer", "guest"].map((r) => (
                <option key={r} value={r}>
                  {t(`roles.${r}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
