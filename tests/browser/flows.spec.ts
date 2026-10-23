import { test, expect } from "@playwright/test";
test("desktop: ремонт, выдача, импорт, роли и документы", async ({ page, context }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Открыть как собственник" }).click();
  await expect(page.getByRole("heading", { name: "Обзор бизнеса." })).toBeVisible({ timeout: 30000 });
  const api = context.request;
  const boot = await (await api.get("/api/v1/bootstrap")).json();
  expect(boot.vehicle.length).toBe(160);
  await page.screenshot({ path: "reports/desktop.png", fullPage: true });
  await page.getByRole("button", { name: "Заявки и сервис 8", exact: true }).click();
  await page.getByRole("button").filter({ hasText: "SRV-201" }).click();
  await page.getByRole("button", { name: "Подготовить смету", exact: true }).click();
  await page.getByLabel("Стоимость работ, ₽").fill("8400");
  await page.getByRole("button", { name: "Подтвердить", exact: true }).click();
  await expect(page.getByRole("button", { name: "Согласовать смету", exact: true })).toBeVisible();
  const command = async (action: string, payload: any) => {
    const r = await api.post("/api/v1/commands", {
      headers: { "Idempotency-Key": crypto.randomUUID() },
      data: { action, payload },
    });
    expect(r.ok(), await r.text()).toBeTruthy();
    return r.json();
  };
  const ticket = boot.ticket.find((t: any) => t.code === "SRV-201");
  await command("ticket.approve", { id: ticket.id });
  await command("ticket.start", { id: ticket.id });
  await command("ticket.complete", { id: ticket.id, amount: "8000" });
  const car = boot.vehicle.find((v: any) => v.id === ticket.vehicle);
  await command("vehicle.inspect", { id: car.id, mileage: car.mileage, fuel: 70 });
  await command("ticket.release", { id: ticket.id });
  const closed = await (await api.get("/api/v1/items/" + ticket.id)).json();
  expect(closed.status).toBe("closed");
  const v = boot.vehicle.find(
    (v: any) =>
      v.direction === "rental" && v.status === "ready" && !boot.bookings.some((b: any) => b.vehicle === v.id),
  );
  const end = new Date(boot.today + "T12:00:00Z");
  end.setDate(end.getDate() + 5);
  const contract = await command("contract.create", {
    vehicle: v.id,
    client: boot.client[0].id,
    start: boot.today,
    end: end.toISOString().slice(0, 10),
  });
  await command("contract.confirm", { id: contract.id });
  await command("contract.issue", { id: contract.id });
  const pdf = await api.get("/api/v1/documents/" + contract.id);
  expect(pdf.headers()["content-type"]).toContain("application/pdf");
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
  const xlsx = await api.get("/api/v1/documents/" + contract.id + "?format=xlsx");
  expect((await xlsx.body()).subarray(0, 2).toString()).toBe("PK");
  const csv = await (await api.get("/api/v1/import/sample")).body();
  const file = await (
    await api.post("/api/v1/files", {
      multipart: { file: { name: "bank.csv", mimeType: "text/csv", buffer: csv } },
    })
  ).json();
  for (let i = 0; i < 2; i++) {
    const preview = await (await api.post("/api/v1/import/preview", { data: { file: file.id } })).json();
    const result = await command("import.commit", { id: preview.id });
    expect(result.posted).toBe(i === 0 ? 4 : 0);
  }
  const before = await (await api.get("/api/v1/report")).json();
  expect(Number(before.expenses)).toBeGreaterThan(8000);
  await page.getByRole("button", { name: "Закрыть карточку", exact: true }).click();
  await page.getByLabel("Демонстрационная роль").selectOption("driver");
  await expect(page.getByRole("heading", { name: "Всё важное — под рукой." })).toBeVisible();
  const own = await (await api.get("/api/v1/bootstrap")).json();
  expect(own.contract.every((c: any) => c.client === own.session.principals.driver)).toBeTruthy();
  const deny = await api.post("/api/v1/commands", {
    headers: { "Idempotency-Key": crypto.randomUUID() },
    data: { action: "payment.create", payload: { contract: own.contract[0].id, amount: 1 } },
  });
  expect(deny.status()).toBe(403);
  expect(errors).toEqual([]);
});
test("mobile: личный кабинет и создание обращения", async ({ page, context }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Открыть как собственник" }).click();
  await expect(page.getByLabel("Демонстрационная роль")).toBeVisible({ timeout: 30000 });
  await page.getByLabel("Демонстрационная роль").selectOption("driver");
  await expect(page.getByRole("heading", { name: "Всё важное — под рукой." })).toBeVisible();
  await page.screenshot({ path: "reports/mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Нужна помощь Ремонт, ТО, вопрос" }).click();
  await page.getByLabel("Тема", { exact: true }).fill("Проверка мобильного обращения");
  await page.getByRole("button", { name: "Подтвердить", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Проверка мобильного обращения" })).toBeVisible();
  const boot = await (await context.request.get("/api/v1/bootstrap")).json();
  expect(boot.ticket.some((t: any) => t.title === "Проверка мобильного обращения")).toBeTruthy();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
