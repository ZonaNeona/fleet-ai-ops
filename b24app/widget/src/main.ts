import { createApp } from "vue";
import App from "./App.vue";
import "./style.css";

declare global {
  interface Window {
    B24APP: { deal: number; key: string; api: string; portal: boolean };
    BX24?: { init: (cb: () => void) => void; fitWindow: () => void };
  }
}

createApp(App).mount("#app");
// Inside a real portal the iframe grows with its content.
window.BX24?.init(() => window.BX24?.fitWindow());
