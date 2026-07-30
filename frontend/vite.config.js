import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy /api requests to the backend container so the frontend code can
// just call fetch("/api/...") without hardcoding a host/port, in dev or prod.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
