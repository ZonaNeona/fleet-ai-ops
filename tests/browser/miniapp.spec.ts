import { test, expect, Page, APIRequestContext } from "@playwright/test";
import { randomUUID } from "node:crypto";
const base = process.env.BASE_URL || "https://fleet.shvarev-demo.ru";

test("SDK adapter: dark theme, safe areas and native button callback", async ({
  page,
}) => {
  await session(page, "client");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    const handlers: Record<string, () => void> = {};
    const sdk: any = {
      initData: "",
      colorScheme: "dark",
      themeParams: {
        bg_color: "#151a1d",
        secondary_bg_color: "#20272b",
        text_color: "#f6f4ef",
        hint_color: "#a1aaa9",
        button_color: "#ae8556",
      },
      safeAreaInset: { top: 12, bottom: 8 },
      contentSafeAreaInset: { top: 0, bottom: 0 },
      ready() {},
      expand() {},
      isVersionAtLeast: () => true,
      onEvent: (event: string, handler: () => void) =>
        (handlers[event] = handler),
      offEvent: (event: string) => delete handlers[event],
      HapticFeedback: { impactOccurred() {}, notificationOccurred() {} },
      MainButton: {
        text: "",
        visible: false,
        enabled: false,
        click: null,
        setText(t: string) {
          this.text = t;
        },
        show() {
          this.visible = true;
        },
        hide() {
          this.visible = false;
        },
        enable() {
          this.enabled = true;
        },
        disable() {
          this.enabled = false;
        },
        showProgress() {},
        hideProgress() {},
        onClick(fn: any) {
          this.click = fn;
        },
        offClick() {
          this.click = null;
        },
      },
      BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
    };
    (window as any).Telegram = { WebApp: sdk };
  });
  await page.goto("/?tg=1#tg/catalog");
  await expect(page.locator("html")).toHaveAttribute("data-tg-theme", "dark");
  await page.locator(".mini-car").first().click();
  await expect
    .poll(() =>
      page.evaluate(() => (window as any).Telegram.WebApp.MainButton.enabled),
    )
    .toBe(true);
  expect(
    await page.evaluate(() =>
      document.documentElement.style.getPropertyValue("--tg-safe-top"),
    ),
  ).toBe("12px");
  await page.screenshot({
    path: "reports/miniapp/client-dark-sdk-adapter.png",
  });
  await page.evaluate(() => (window as any).Telegram.WebApp.MainButton.click());
  await expect(page.locator(".mini-badge").first()).toContainText("Резерв");
  await expect
    .poll(() =>
      page.evaluate(() => (window as any).Telegram.WebApp.MainButton.visible),
    )
    .toBe(false);
});

test("existing desktop dashboard and Under Hood remain accessible", async ({
  page,
}) => {
  await post(page.request, "/session", {});
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Обзор бизнеса." }),
  ).toBeVisible();
  await page
    .locator(".topbar")
    .getByRole("button", { name: "Под капотом" })
    .click();
  await expect(page.locator(".k-shell")).toBeVisible();
  await page.locator(".k-rail button", { hasText: "Журнал" }).click();
  await expect(page).toHaveURL(/#under\/log$/);
  await page.reload();
  await expect(page.locator(".k-rail button.active")).toContainText("Журнал");
});

async function post(request: APIRequestContext, path: string, body: unknown) {
  const r = await request.post(base + "/api/v1" + path, {
    data: body,
    headers: { Origin: base },
  });
  expect(r.ok(), await r.text()).toBeTruthy();
  return r.json();
}
async function cmd(
  request: APIRequestContext,
  action: string,
  payload: unknown,
  key = randomUUID(),
) {
  const r = await request.post(base + "/api/v1/commands", {
    data: { action, payload },
    headers: { Origin: base, "Idempotency-Key": key },
  });
  expect(r.ok(), await r.text()).toBeTruthy();
  return r.json();
}
async function sim(request: APIRequestContext, payload: unknown) {
  const j = await post(request, "/bot/sim", payload);
  let result: any;
  await expect
    .poll(
      async () => {
        result = await (
          await request.get(base + "/api/v1/bot/sim/" + j.id)
        ).json();
        return result.state;
      },
      { timeout: 60000, intervals: [300, 500, 1000] },
    )
    .toBe("done");
  return result.result;
}
async function session(page: Page, role: string) {
  await post(page.request, "/session", {});
  await sim(page.request, { text: "/start" });
  await sim(page.request, { callback: "pd:yes" });
  await sim(page.request, { callback: "role:" + role });
}

test("client: phone → booking → manager → deposit → one ledger entry", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("button", { name: /Бот и кабинет клиента/ }).click();
  const phone = page.locator(".phone");
  await phone.getByRole("button", { name: "СТАРТ", exact: true }).click();
  await phone.getByRole("button", { name: "✅ Согласен", exact: true }).click();
  await phone
    .getByRole("button", { name: /Демо: выбрать роль вручную/ })
    .click();
  await phone
    .getByRole("button", { name: /Я клиент проката/ })
    .last()
    .click();
  await phone
    .getByRole("button", { name: /Кабинет клиента/ })
    .last()
    .click();
  const mini = page.frameLocator('iframe[title="Кабинет таксопарка"]');
  await expect(mini.locator(".mini-car").first()).toBeVisible();
  await page.evaluate(() => (document.documentElement.dataset.theme = "dark"));
  await expect(mini.locator("html")).toHaveAttribute("data-tg-theme", "dark");
  await page.evaluate(() => (document.documentElement.dataset.theme = "light"));
  await expect(mini.locator("html")).toHaveAttribute("data-tg-theme", "light");
  await page.screenshot({ path: "reports/miniapp/client-phone.png" });
  await mini.locator(".mini-car").first().click();
  await mini.getByRole("button", { name: /7 дней/ }).click();
  await expect(mini.locator(".mini-positive")).toHaveText("−5%");
  const reserve = page.locator(".phone-mini-action button");
  await expect(reserve).toBeEnabled();
  await expect(reserve).toContainText("Забронировать за");
  await page.screenshot({ path: "reports/miniapp/client-quote.png" });
  await reserve.click();
  await expect(mini.locator(".mini-badge").first()).toContainText("Резерв");
  const frame = page.frames().find((f) => f.url().includes("#tg/rentals/"))!;
  const id = frame.url().split("#tg/rentals/")[1];
  expect(id).toMatch(/^[a-f0-9]{32}$/);
  await page.getByLabel("Демонстрационная роль").selectOption("manager");
  await expect(page.getByLabel("Демонстрационная роль")).toHaveValue("manager");
  await expect(page.locator(".phone-mini")).toHaveCount(0);
  const boot = await (
    await page.request.get(base + "/api/v1/bootstrap")
  ).json();
  const booking = boot.contract.find((c: any) => c.id === id);
  expect(booking).toBeTruthy();
  await cmd(page.request, "contract.confirm", { id });
  await page.getByLabel("Демонстрационная роль").selectOption("client");
  await expect(page.getByLabel("Демонстрационная роль")).toHaveValue("client");
  await page.getByRole("button", { name: "Telegram-бот", exact: true }).click();
  await phone
    .getByRole("button", { name: /Кабинет клиента/ })
    .last()
    .click();
  await mini.getByRole("button", { name: "Мои аренды", exact: true }).click();
  await mini.locator(".mini-rental", { hasText: booking.code }).click();
  await mini.getByRole("button", { name: /Оплатить залог/ }).click();
  await expect(mini.locator(".mini-pay")).toContainText("ТЕСТОВЫЙ РЕЖИМ");
  // Response loss: replay must return the same committed operation.
  let dropped = false;
  await page.route("**/api/v1/commands", async (route) => {
    const body = route.request().postDataJSON();
    if (body.action === "demo_payment.confirm" && !dropped) {
      dropped = true;
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await expect(reserve).toContainText("Подтвердить учебную оплату");
  await reserve.click();
  await expect(mini.getByRole("alert")).toBeVisible();
  await reserve.click();
  await expect(
    mini.getByRole("heading", { name: "Оплата проведена" }),
  ).toBeVisible();
  await page.screenshot({
    path: "reports/miniapp/client-receipt-phone.png",
  });
  const receiptUrl = await mini
    .getByRole("link", { name: /Скачать квитанцию/ })
    .getAttribute("href");
  const pdf = await page.request.get(base + receiptUrl);
  expect(pdf.headers()["content-type"]).toContain("application/pdf");
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
  await post(page.request, "/session/role", { role: "finance" });
  const ledger = await (
    await page.request.get(base + "/api/v1/ledger?contract=" + id)
  ).json();
  expect(
    ledger.rows.filter((e: any) => e.contract === id && e.kind === "deposit"),
  ).toHaveLength(1);
  expect(errors).toEqual([]);
});

test("mobile: documents, offline payment guard and second visitor isolation", async ({
  page,
  browser,
}) => {
  await session(page, "client");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?tg=1#tg/profile");
  await page.getByLabel("Загрузить: Паспорт", { exact: true }).setInputFiles({
    name: "demo-passport.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\nУчебный документ\n%%EOF"),
  });
  await expect(page.getByText("demo-passport.pdf")).toBeVisible();
  const fileUrl = await page
    .locator(".mini-document")
    .first()
    .getByRole("link", { name: "Открыть" })
    .getAttribute("href");
  expect(fileUrl).toMatch(/api\/v1\/files/);
  await page.screenshot({
    path: "reports/miniapp/client-documents-mobile.png",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  const other = await browser.newContext();
  await post(other.request, "/session", {});
  expect((await other.request.get(base + fileUrl)).status()).toBe(404);
  await other.close();
  await page.context().setOffline(true);
  await expect(page.getByRole("status")).toContainText("Нет сети");
  await expect(
    page.getByLabel("Загрузить: Паспорт", { exact: true }),
  ).toBeDisabled();
  await page.context().setOffline(false);
});

test("driver: n8n fine, payment, accident and four-photo inspection", async ({
  page,
}) => {
  await session(page, "driver");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?tg=1#tg/driver");
  await expect(page.locator(".mini-balance")).toBeVisible();
  await page.screenshot({ path: "reports/miniapp/driver-home-mobile.png" });
  const payRent = page.getByRole("button", { name: /^Оплатить ·/ }).first();
  await expect(payRent).toBeVisible();
  {
    await payRent.click();
    await page
      .getByRole("button", { name: /Подтвердить учебную оплату/ })
      .click();
    await expect(
      page.getByRole("heading", { name: "Оплата проведена" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Вернуться в кабинет" }).click();
  }
  await page.getByRole("button", { name: "Штрафы", exact: true }).click();
  await page.getByRole("button", { name: "Обновить из источника" }).click();
  await expect(
    page.getByRole("button", { name: /Оплатить со скидкой/ }).first(),
  ).toBeVisible({ timeout: 60000 });
  await page.screenshot({ path: "reports/miniapp/driver-fines-mobile.png" });
  await page
    .getByRole("button", { name: /Оплатить со скидкой/ })
    .first()
    .click();
  await page
    .getByRole("button", { name: /Подтвердить учебную оплату/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "Оплата проведена" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Вернуться в кабинет" }).click();
  await page.getByRole("button", { name: "Помощь", exact: true }).click();
  await page.getByRole("button", { name: /Сообщить о ДТП/ }).click();
  await page
    .getByLabel("Адрес или координаты")
    .fill("Учебный адрес: Москва, Митинская, 1");
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  const image = {
    name: "demo-photo.png",
    mimeType: "image/png",
    buffer: await page.locator(".mini-brand").screenshot(),
  };
  await page
    .getByLabel("Фото: Общий план", { exact: true })
    .setInputFiles(image);
  await expect(page.getByText("Фото загружено")).toBeVisible();
  await page
    .getByLabel("Обстоятельства происшествия")
    .fill("Учебный осмотр после касания ограждения. Небольшая царапина.");
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await page
    .getByRole("button", { name: "Отправить обращение в сервис", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "ДТП · обращение водителя" }),
  ).toBeVisible();
  await page.screenshot({ path: "reports/miniapp/driver-accident-mobile.png" });
  await page.goto("/?tg=1#tg/driver/inspection");
  for (const side of ["Спереди", "Сзади", "Слева", "Справа"]) {
    await page
      .getByLabel("Фото: " + side, { exact: true })
      .setInputFiles({ ...image, name: side + ".png" });
    await expect(
      page.getByLabel("Фото: " + side, { exact: true }),
    ).toBeEnabled();
  }
  await expect(page.getByText("Фото загружено")).toHaveCount(4);
  await page
    .getByLabel("Замечания, если есть")
    .fill("Учебная отметка: проверить правое зеркало");
  await page
    .getByRole("button", { name: "Сохранить предсменный осмотр" })
    .click();
  await expect(page.locator(".mini-balance")).toBeVisible();
  const boot = await (
    await page.request.get(base + "/api/v1/bootstrap")
  ).json();
  expect(
    boot.inspection.some(
      (i: any) => i.subtype === "pre_shift" && i.photos.length === 4,
    ),
  ).toBeTruthy();
  expect(
    boot.ticket.some((i: any) => i.title === "Замечания предсменного осмотра"),
  ).toBeTruthy();
});
