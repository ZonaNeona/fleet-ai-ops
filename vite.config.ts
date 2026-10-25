import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// API_TARGET=https://fleet.shvarev-demo.ru: develop the frontend against the live API
// (Origin is rewritten to the stand's address: the server accepts writes only from its own origin)
const target = process.env.API_TARGET || "http://127.0.0.1:3008";
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": { target, changeOrigin: true, secure: true, headers: { origin: target } } } },
});
