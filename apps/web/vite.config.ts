/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// API, které se NIKDY necachuje (přihlášení, AI, proud událostí, štítky/PDF): žádné runtime pravidlo
// je nezachytí, takže jdou vždy rovnou na síť. Zápisy (POST/PATCH/PUT/DELETE) se necachují nikdy.
// POZOR: funkce urlPattern se serializují do service workeru – nesmí používat proměnné z tohoto souboru.

// Dev: /api se proxuje na FastAPI (port 8000). V produkci to řeší reverzní proxy.
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "prompt", // novou verzi nabídneme tlačítkem, ať se nepřerušuje rozdělaná práce
      injectRegister: false, // registraci řeší komponenta UpdatePrompt
      includeAssets: ["icons/apple-touch-icon.png", "icons/favicon-48.png"],
      manifest: {
        name: "Domovník",
        short_name: "Domovník",
        description: "Domácí inventář s AI asistentem",
        lang: "cs",
        dir: "ltr",
        start_url: "/",
        scope: "/",
        display: "standalone",
        orientation: "portrait",
        background_color: "#f8fafc",
        theme_color: "#0f8a66",
        categories: ["productivity", "utilities"],
        icons: [
          { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          {
            src: "/icons/maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
        shortcuts: [
          { name: "Skenovat štítek", url: "/scan", icons: [] },
          { name: "Inventura", url: "/inventory", icons: [] },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,webmanifest}"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//],
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          {
            // Čtení dat: nejdřív síť (vždy čerstvá data po úpravě), při výpadku uložená kopie.
            urlPattern: ({ url, request }) =>
              request.method === "GET" &&
              /^\/api\/v1\/(items|locations|categories|tags|stats|settings)(\/|$)/.test(
                url.pathname,
              ),
            handler: "NetworkFirst",
            options: {
              cacheName: "domovnik-api",
              networkTimeoutSeconds: 4,
              cacheableResponse: { statuses: [200] },
              expiration: { maxEntries: 300, maxAgeSeconds: 60 * 60 * 24 * 30 },
            },
          },
          {
            // Náhledy fotek se po nahrání nemění (adresované obsahem) → cache first.
            urlPattern: ({ url, request }) =>
              request.method === "GET" && /^\/api\/v1\/files\/[^/]+\/thumb$/.test(url.pathname),
            handler: "CacheFirst",
            options: {
              cacheName: "domovnik-thumbs",
              cacheableResponse: { statuses: [200] },
              expiration: { maxEntries: 500, maxAgeSeconds: 60 * 60 * 24 * 30 },
            },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.API_TARGET ?? "http://localhost:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
});
