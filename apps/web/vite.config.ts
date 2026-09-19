import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs as a separate process; the dev server proxies to it so the app is same-origin in
// development and in the packaged build alike. No stage-network dependency: everything is local.
export default defineConfig({
  root: ".",
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.DRONEBENCH_API ?? "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
  build: { outDir: "dist", sourcemap: true },
});
