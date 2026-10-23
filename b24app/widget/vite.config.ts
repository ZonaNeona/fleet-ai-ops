import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Built into the PHP app's public folder under fixed names; index.php adds the file time for cache busting.
export default defineConfig({
  plugins: [vue()],
  base: "./",
  build: {
    outDir: "../public/widget",
    emptyOutDir: true,
    rollupOptions: {
      input: "src/main.ts",
      output: { entryFileNames: "app.js", assetFileNames: "app[extname]" },
    },
  },
});
