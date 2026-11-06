import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { post } from "../../api/client";
import { Button, Field, Input, errorMessage } from "../../components/ui";
import { AuthShell } from "./LoginPage";

/** Úvodní nastavení: vytvoří prvního (administrátorského) uživatele. */
export default function SetupPage({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const mismatch = again.length > 0 && again !== password;
  const tooShort = password.length > 0 && password.length < 10;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/auth/setup", { username, display_name: displayName, password });
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell title={t("auth.setupTitle")}>
      <p className="text-sm text-slate-500">{t("auth.setupHint")}</p>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t("auth.username")}>
          {(id) => (
            <Input
              id={id}
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("auth.displayName")}>
          {(id) => (
            <Input id={id} value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          )}
        </Field>
        <Field
          label={t("auth.password")}
          hint={t("auth.passwordHint")}
          error={tooShort ? t("auth.passwordHint") : null}
        >
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
        <Field
          label={t("auth.passwordAgain")}
          error={mismatch ? t("auth.passwordMismatch") : error}
        >
          {(id) => (
            <Input
              id={id}
              type="password"
              autoComplete="new-password"
              value={again}
              onChange={(e) => setAgain(e.target.value)}
            />
          )}
        </Field>
        <Button
          type="submit"
          variant="primary"
          className="w-full"
          disabled={busy || !username || password.length < 10 || password !== again}
        >
          {t("auth.setupSubmit")}
        </Button>
      </form>
    </AuthShell>
  );
}
