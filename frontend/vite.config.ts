import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, Vite serves the UI on :5173 and forwards /api to FastAPI on :8000.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
});
