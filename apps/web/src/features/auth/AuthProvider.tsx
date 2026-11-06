import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, createContext, useCallback, useContext, useEffect, useMemo } from "react";

import { get, post, setCsrfToken, setUnauthorizedHandler } from "../../api/client";
import type { AuthStatus, Me } from "../../api/types";
import { Spinner } from "../../components/ui";
import { clearOfflineData, isNetworkError, recallMe, rememberMe } from "../../lib/offlineCache";
import LoginPage from "./LoginPage";
import SetupPage from "./SetupPage";

interface AuthValue {
  me: Me;
  isAdmin: boolean;
  can: (scope: string) => boolean;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const v = useContext(AuthContext);
  if (!v) throw new Error("useAuth mimo AuthProvider");
  return v;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["auth", "status"],
    queryFn: () => get<AuthStatus>("/auth/status"),
    retry: false,
  });
  const authenticated = status.data?.authenticated === true;
  const me = useQuery({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      const m = await get<Me>("/auth/me");
      setCsrfToken(m.csrf_token);
      rememberMe(m);
      return m;
    },
    enabled: authenticated,
    retry: false,
  });

  const reset = useCallback(() => {
    setCsrfToken(null);
    void clearOfflineData(); // po odhlášení / vypršení relace nezůstávají data pro offline
    // data starého přihlášení zahodit, stav přihlášení znovu načíst
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
    void qc.invalidateQueries({ queryKey: ["auth"] });
  }, [qc]);

  useEffect(() => {
    setUnauthorizedHandler(reset);
    return () => setUnauthorizedHandler(null);
  }, [reset]);

  const logout = useCallback(async () => {
    await post("/auth/logout");
    reset();
  }, [reset]);

  // Bez spojení se aplikace otevře s naposledy známým uživatelem a daty uloženými service workerem.
  const offlineMe = useMemo(
    () => (status.isError && isNetworkError(status.error) ? recallMe() : null),
    [status.isError, status.error],
  );
  const effectiveMe = me.data ?? offlineMe;

  const value = useMemo<AuthValue | null>(() => {
    if (!effectiveMe) return null;
    const scopes = new Set(effectiveMe.scopes);
    return {
      me: effectiveMe,
      isAdmin: effectiveMe.user.role === "admin",
      can: (s) => scopes.has(s) || scopes.has("admin"),
      logout,
    };
  }, [effectiveMe, logout]);

  if (status.isPending) return <Spinner label="Načítám…" />;
  if (offlineMe && value) {
    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
  }
  if (status.isError && !status.data) {
    return (
      <div className="p-6" role="alert">
        API není dostupné. Zkontroluj, že server běží.
      </div>
    );
  }
  if (!status.data) return <Spinner label="Načítám…" />;
  if (status.data.setup_required) return <SetupPage onDone={reset} />;
  if (!authenticated) return <LoginPage onDone={reset} />;
  if (!value) return <Spinner label="Načítám…" />;
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
