// Скриншоты контура «Под капотом»: node scripts/under_shots.mjs [baseURL] [outDir] [шаги через запятую]
import { chromium } from "@playwright/test";
const base = process.argv[2] || "http://localhost:5174";
const out = process.argv[3] || "reports";
const only = (process.argv[4] || "map,rag,agent,n8n,log,mobile").split(",");
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
p.on("pageerror", (e) => errors.push(e.message));
const shot = (name) => p.screenshot({ path: `${out}/under-${name}.png` });
await p.goto(base + "/");
await p.getByRole("button", { name: "Открыть как собственник", exact: true }).click();
await p.getByRole("heading", { name: "Обзор бизнеса." }).waitFor({ timeout: 40000 });
await p.getByRole("button", { name: "Под капотом" }).first().click();
await p.locator(".k-shell").waitFor();
const section = (name) => p.locator(".k-rail button", { hasText: name }).click();
const engineer = (on) => p.getByRole("button", { name: on ? "Инженер" : "Просто" }).click();
if (only.includes("fab")) {
  await p.waitForTimeout(1500);
  await shot("fab-console");
  await p.locator(".ask-fab").click();
  await p.locator(".ai-drawer").waitFor();
  await p.waitForTimeout(600);
  await shot("fab-console-panel");
  await p.keyboard.press("Escape");
  await p.locator(".k-top").getByRole("button", { name: "Продукт" }).click();
  await p.waitForTimeout(1500);
  await shot("fab-product");
  await p
    .getByRole("button", { name: /тёмн.*тем|Тёмная|темн/i })
    .first()
    .click()
    .catch(() => {});
  await p.waitForTimeout(800);
  await shot("fab-product-dark");
  await p.setViewportSize({ width: 390, height: 844 });
  await p.waitForTimeout(800);
  await shot("fab-product-mobile");
  await p.setViewportSize({ width: 1440, height: 900 });
  await p.locator(".topbar").getByRole("button", { name: "Под капотом" }).click();
  await p.waitForTimeout(1000);
}
if (only.includes("map")) {
  await p.waitForTimeout(800);
  await shot("map");
  await p.getByRole("button", { name: "Синхронизация с 1С" }).first().click();
  await p.waitForTimeout(4800);
  await shot("map-run");
}
if (only.includes("rag")) {
  await section("RAG");
  await p.getByRole("button", { name: "Какие документы нужны водителю?" }).click();
  await p.locator(".k-tl-step").first().waitFor({ timeout: 90000 });
  await p.waitForTimeout(3500);
  await shot("rag-run");
  await p.waitForTimeout(9000);
  await engineer(true);
  await p.locator(".react-flow__node", { hasText: "Слияние" }).click();
  await p.waitForTimeout(600);
  await shot("rag-eng");
  await engineer(false);
}
if (only.includes("agent")) {
  await section("Агент");
  await p.getByRole("button", { name: "Какие 3 машины дают самый низкий результат и почему?" }).click();
  await p.locator(".k-tl-step").first().waitFor({ timeout: 120000 });
  await p.waitForTimeout(2600);
  await shot("agent-run");
  await p.waitForTimeout(9000);
  await shot("agent-done");
}
if (only.includes("n8n")) {
  await section("Интеграции");
  await p.waitForTimeout(800);
  await p.getByRole("button", { name: "Запустить workflow" }).click();
  await p.locator(".k-tl-step").first().waitFor({ timeout: 60000 });
  await p.waitForTimeout(3000);
  await shot("n8n-run");
  await p.waitForTimeout(8000);
  await shot("n8n-done");
}
if (only.includes("log")) {
  await section("Журнал");
  await p.locator(".k-log-row").first().waitFor({ timeout: 20000 });
  await p.locator(".k-log-row").first().click();
  await p.waitForTimeout(500);
  await shot("log");
}
if (only.includes("mobile")) {
  await p.setViewportSize({ width: 390, height: 844 });
  await section("Карта");
  await p.waitForTimeout(1000);
  await shot("mobile-map");
  await p.getByRole("button", { name: "Продукт" }).click();
  await p.waitForTimeout(1200);
  await shot("mobile-product");
}
console.log("errors:", JSON.stringify(errors));
await b.close();
