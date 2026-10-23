import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// API_TARGET=https://fleet.shvarev-demo.ru — разработка фронтенда против живого API
// (Origin подменяем на адрес стенда: сервер принимает изменения только со своего источника)
const target = process.env.API_TARGET || "http://127.0.0.1:3008";
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": { target, changeOrigin: true, secure: true, headers: { origin: target } } } },
});
