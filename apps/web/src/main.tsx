import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import UpdatePrompt from "./components/UpdatePrompt";
import { ToastProvider } from "./components/ui";
import { AuthProvider } from "./features/auth/AuthProvider";
import "./i18n";
import "./lib/install"; // zachytí nabídku instalace dřív, než se vykreslí React
import "./index.css";

// offlineFirst: dotazy se vždy pokusí o síť a při výpadku je obslouží service worker (uložená kopie);
// mutace selžou hned (srozumitelná chyba), místo aby tiše čekaly na připojení.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 1,
      refetchOnWindowFocus: true,
      networkMode: "offlineFirst",
    },
    mutations: { networkMode: "always" },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
          <UpdatePrompt />
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
