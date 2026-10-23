import { test, expect } from "@playwright/test";

// Контур «Под капотом» — отдельная оболочка, включается переключателем в шапке и по #under/<раздел>.
test("under hood: header switch and anchors swap the whole shell", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Открыть как собственник", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Обзор бизнеса." })).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".sidebar")).not.toContainText("Под капотом");
  await page.locator(".topbar").getByRole("button", { name: "Под капотом" }).click();
  await expect(page.locator(".k-shell")).toBeVisible();
  await expect(page.locator(".sidebar")).toHaveCount(0);
  await expect(page).toHaveURL(/#under\/map$/);
  await page.locator(".k-rail button", { hasText: "RAG" }).click();
  await expect(page).toHaveURL(/#under\/rag$/);
  await page.reload();
  await expect(page.locator(".k-rail button.active")).toContainText("RAG");
  await page.locator(".k-top").getByRole("button", { name: "Продукт" }).click();
  await expect(page.getByRole("heading", { name: "Обзор бизнеса." })).toBeVisible();
  await page.goto("/#under/log");
  await expect(page.locator(".k-rail button.active")).toContainText("Журнал");
});

test("under hood: real RAG, role-bound agent, n8n replay and mobile", async ({ page }) => {
  test.setTimeout(240000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Открыть как собственник", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Обзор бизнеса." })).toBeVisible({ timeout: 30000 });
  await page.locator(".topbar").getByRole("button", { name: "Под капотом" }).click();

  // карта: сценарий проигрывается по шагам
  await page.getByRole("button", { name: "Водитель спрашивает долг в боте" }).first().click();
  await expect(page.locator(".k-caption")).toBeVisible();
  await page.screenshot({ path: "reports/under-map.png" });

  // RAG: реальная трасса, ответ со ссылками
  await page.locator(".k-rail button", { hasText: "RAG" }).click();
  await page.getByRole("button", { name: "Какие документы нужны водителю?", exact: true }).click();
  await expect(page.locator(".k-tl-step").first()).toBeVisible({ timeout: 90000 });
  await expect(page.locator(".k-tl-step", { hasText: "Ссылки" })).toBeVisible();
  await expect(page.locator(".k-answer")).toContainText(/паспорт/i, { timeout: 20000 });
  await page.screenshot({ path: "reports/under-rag.png" });
  await page.getByRole("button", { name: "Инженер" }).click();
  await page.locator(".react-flow__node", { hasText: "Слияние" }).click();
  await expect(page.locator(".k-inspector")).toContainText("Reciprocal Rank Fusion");

  // агент: роль водителя видит get_balance, у менеджера он под замком
  await page.locator(".k-rail button", { hasText: "Агент" }).click();
  await page.getByRole("button", { name: "Сколько я должен?", exact: true }).click();
  await expect(page.locator(".k-tl-step", { hasText: "get_balance" })).toBeVisible({ timeout: 90000 });
  await page.screenshot({ path: "reports/under-agent.png" });
  await page.locator(".k-role").selectOption("manager");
  await expect(page.locator(".react-flow__node", { hasText: "get_balance" })).toContainText("нет доступа у роли");
  await page.locator(".k-role").selectOption("owner");

  // интеграции: настоящий запуск n8n и сверка
  await page.locator(".k-rail button", { hasText: "Интеграции" }).click();
  await page.getByRole("button", { name: "Запустить workflow" }).click();
  await expect(page.locator(".k-tl-step", { hasText: "Нормализовать данные" })).toBeVisible({ timeout: 60000 });
  await expect(page.locator(".k-inspector")).toContainText("расхождений", { timeout: 20000 });
  await page.screenshot({ path: "reports/under-n8n.png" });

  // журнал и переход «проиграть на холсте»
  await page.locator(".k-rail button", { hasText: "Журнал" }).click();
  await page.locator(".k-log-row", { hasText: "Сколько я должен?" }).first().click();
  await page.getByRole("button", { name: "Проиграть на холсте" }).click();
  await expect(page.locator(".k-rail button.active")).toContainText("Агент");
  await page.screenshot({ path: "reports/under-log-replay.png" });

  // телефон: без горизонтальной прокрутки, рейка внизу
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator(".k-rail button", { hasText: "Карта" }).click();
  await page.screenshot({ path: "reports/under-mobile-map.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.locator(".k-top").getByRole("button", { name: "Продукт" }).click();
  await expect(page.locator(".sources-widget, .uh-sources-widget")).toBeVisible({ timeout: 20000 });
  expect(errors).toEqual([]);
});
