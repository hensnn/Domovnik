import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { post } from "../../api/client";
import { Button, Field, Input, errorMessage } from "../../components/ui";

export function AuthShell({ title, children }: { title: string; children: React.ReactNode }) {
  const { t } = useTranslation();
  return (
    <main className="flex min-h-full items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-brand-600">{t("app.name")}</h1>
          <p className="text-sm text-slate-500">{t("app.tagline")}</p>
        </div>
        <div className="space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-lg font-semibold">{title}</h2>
          {children}
        </div>
      </div>
    </main>
  );
}

export default function LoginPage({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/auth/login", { username, password });
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell title={t("auth.login")}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t("auth.username")}>
          {(id) => (
            <Input
              id={id}
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("auth.password")} error={error}>
          {(id) => (
            <Input
              id={id}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
        </Field>
        <Button
          type="submit"
          variant="primary"
          className="w-full"
          disabled={busy || !username || !password}
        >
          {t("auth.login")}
        </Button>
      </form>
    </AuthShell>
  );
}
