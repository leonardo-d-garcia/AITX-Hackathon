import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@telemetry": path.resolve(
        root,
        "../../fixtures/c/synthetic_vtail_demo/simulation_run.json",
      ),
    },
  },
  server: {
    port: 5173,
    fs: {
      allow: [path.resolve(root, "../..")],
    },
  },
});
