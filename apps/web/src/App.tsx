import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { fetchHealth } from "./api";

export default function App() {
  const { t } = useTranslation();
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, retry: false });

  return (
    <main className="mx-auto max-w-xl p-6">
      <h1 className="text-3xl font-bold">{t("app.name")}</h1>
      <p className="text-slate-600">{t("app.tagline")}</p>

      <section className="mt-6 rounded-lg border border-slate-200 p-4">
        <h2 className="font-semibold">{t("health.title")}</h2>
        {health.isPending && <p>{t("health.loading")}</p>}
        {health.isError && <p role="alert">{t("health.error")}</p>}
        {health.isSuccess && <p>{t("health.ok", { version: health.data.version })}</p>}
      </section>
    </main>
  );
}
