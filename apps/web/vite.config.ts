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
        "../../fixtures/c/titan_avenger_cad/simulation_run.json",
      ),
      "@airframe": path.resolve(
        root,
        "../../fixtures/c/titan_avenger_cad/meshes/titan_avenger.glb",
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
