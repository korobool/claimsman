import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// Build output lands inside the FastAPI app's static directory so the single
// Python process can serve the SPA at /app.
export default defineConfig({
  plugins: [react()],
  base: "/app/",
  build: {
    outDir: resolve(__dirname, "../web/static/app"),
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8811",
    },
  },
});
