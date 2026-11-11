import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The built app is served by Flask under /app. In development Vite runs on 5173 and
// forwards API calls (and, from Phase 6, Socket.IO) to the Flask backend on 5000.
export default defineConfig({
  base: "/app/",
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5000",
      "/socket.io": { target: "http://127.0.0.1:5000", ws: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
