export type Row = { id: string; code: string; version: number; kind: string; [key: string]: any };
export type Data = {
  session: { id: string; role: string; roles: Record<string, string>; principals: Record<string, any> };
  vehicle: Row[];
  client: Row[];
  contract: Row[];
  ticket: Row[];
  investor: Row[];
  statement: Row[];
  tariff: Row[];
  referral: Row[];
  inspection: Row[];
  import: Row[];
  knowledge: Row[];
  document: Row[];
  bookings: Row[];
  branches: Row[];
  sources: Row[];
  today: string;
  telegram_username: string | null;
  ai_configured: boolean;
};
export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    ...((options.headers as Record<string, string>) || {}),
  };
  const r = await fetch("/api/v1" + path, { ...options, headers, credentials: "same-origin" });
  if (!r.ok) {
    let detail = "Сервис временно недоступен";
    try {
      const v = await r.json();
      detail = typeof v.detail === "string" ? v.detail : JSON.stringify(v.detail);
    } catch {}
    throw Object.assign(new Error(detail), { status: r.status });
  }
  return r.json();
}
export const rub = (x: any, compact = false) =>
  new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 0,
    ...(compact ? { notation: "compact" as const } : {}),
  }).format(Number(x || 0));
export const num = (x: any) => new Intl.NumberFormat("ru-RU").format(Number(x || 0));
export const dt = (x: string) =>
  x
    ? new Date(x.length === 10 ? x + "T12:00:00" : x).toLocaleDateString("ru-RU", {
        day: "numeric",
        month: "short",
      })
    : "—";
export const dirs: Record<string, string> = {
  taxi: "Таксопарк",
  rental: "Прокат",
  commercial: "Коммерческий",
  buyout: "Выкуп",
};
export const statuses: Record<string, string> = {
  ready: "Готов к выдаче",
  repair: "В ремонте",
  inspection: "Ожидает осмотр",
  sold: "Передан владельцу",
  active: "Действует",
  draft: "Черновик",
  confirmed: "Подтверждён",
  completed: "Завершён",
  cancelled: "Отменён",
  bought: "Выкуплен",
  new: "Новое",
  review: "На проверке",
  approved: "Согласовано",
  rejected: "Отклонено",
  estimate: "Смета",
  quality: "Контроль качества",
  closed: "Закрыто",
  paid: "Выплачено",
  pending: "Ожидает",
  preview: "Предпросмотр",
  hold: "Резерв",
  technical: "Техническое",
  urgent: "Срочно",
  normal: "Обычное",
  company: "Компания",
  driver: "Водитель",
  owner: "Владелец",
  insurance: "Страхование",
};
export const kinds: Record<string, string> = {
  fine_payment: "Учебная оплата штрафа",
  charge: "Начисление",
  payment: "Оплата",
  expense: "Расход",
  deposit: "Залог",
  deposit_release: "Освобождение залога",
  cash_refund: "Возврат залога",
  receivable: "Ожидаемое возмещение",
  owner_payout: "Выплата владельцу",
  overhead: "Общие расходы",
  bonus: "Бонус",
};
export const financialRoles = ["owner", "admin", "finance", "investor", "driver", "client"];
export const staffRoles = ["owner", "admin", "finance", "manager", "service", "screening"];
export function getLabel(data: Data, id?: string) {
  if (!id) return "—";
  for (const kind of ["vehicle", "client", "contract", "investor"] as const) {
    const r = data[kind].find((x) => x.id === id);
    if (r) return r.model ? `${r.model} · ${r.code}` : r.name || r.code;
  }
  return "—";
}
export function availableActions(x: Row, role: string): { id: string; label: string }[] {
  const all = role === "admin" || role === "owner";
  const ok = (roles: string[]) => all || roles.includes(role);
  const a: { id: string; label: string }[] = [];
  const add = (id: string, label: string, roles: string[]) => {
    if (ok(roles)) a.push({ id, label });
  };
  if (x.kind === "vehicle") {
    add("vehicle.inspect", "Провести осмотр", ["manager", "service"]);
    add("vehicle.transfer", "Переместить", ["manager"]);
    add("ticket.create", "Создать обращение", ["manager", "driver", "client", "service"]);
  }
  if (x.kind === "client") {
    add("client.documents", "Комплект документов", ["manager", "screening", "driver", "client"]);
    if (x.status === "review") add("client.review", "Решение по проверке", ["screening"]);
  }
  if (x.kind === "contract") {
    if (x.status === "draft") {
      if (x.direction === "buyout" && x.terms_approved === false)
        add("contract.approve_terms", "Утвердить предложение выкупа", ["finance"]);
      else add("contract.confirm", "Подтвердить договор", ["manager"]);
    }
    if (x.status === "confirmed") add("contract.issue", "Выдать автомобиль", ["manager"]);
    if (["draft", "confirmed"].includes(x.status)) add("contract.cancel", "Отменить бронь", ["manager", "client"]);
    if (["active", "confirmed"].includes(x.status)) add("contract.extend", "Продлить аренду", ["manager"]);
    if (x.status === "active") {
      add("payment.create", "Зачислить оплату", ["finance"]);
      if (x.direction !== "buyout") add("contract.return", "Оформить возврат", ["manager"]);
      add("contract.holiday", "Запросить каникулы", ["driver", "manager"]);
      add("contract.schedule", "Изменить график", ["driver", "manager"]);
      if (x.holiday_request?.length) add("contract.approve_holiday", "Согласовать каникулы", ["finance"]);
      if (x.schedule_request) add("contract.approve_schedule", "Согласовать график", ["finance"]);
      if (x.direction === "buyout") {
        add("contract.close_request", "Запросить досрочный выкуп", ["driver", "manager"]);
        add("contract.close_quote", "Утвердить расчёт выкупа", ["finance"]);
        if (x.close_quote) add("contract.close", "Завершить выкуп", ["finance"]);
      }
    }
    if (Number(x.deposit) > 0) {
      add("deposit.refund", "Вернуть залог", ["finance"]);
      add("deposit.withhold", "Удержать из залога", ["finance"]);
    }
  }
  if (x.kind === "ticket") {
    if (["new", "estimate", "approved"].includes(x.status))
      add("ticket.schedule", "Записать в сервис", ["manager", "service"]);
    if (["approved", "repair", "quality"].includes(x.status) && x.contract && !x.substitute_contract)
      add("ticket.substitute", "Оформить подмену", ["manager"]);
    if (["new", "estimate"].includes(x.status)) add("ticket.estimate", "Подготовить смету", ["service"]);
    if (x.status === "estimate") add("ticket.approve", "Согласовать смету", ["finance", "investor"]);
    if (x.status === "approved") add("ticket.start", "Начать ремонт", ["service"]);
    if (x.status === "repair") add("ticket.complete", "Завершить ремонт", ["service"]);
    if (x.status === "quality") add("ticket.release", "Вернуть в работу", ["service"]);
  }
  if (x.kind === "investor") add("owner.statement", "Сформировать отчёт", ["finance"]);
  if (x.kind === "statement") {
    if (x.status === "draft") add("owner.approve", "Утвердить отчёт", ["finance"]);
    if (x.status === "approved") add("owner.pay", "Зарегистрировать выплату", ["finance"]);
  }
  if (x.kind === "referral" && x.status === "pending") add("referral.approve", "Начислить бонус", ["finance"]);
  if (x.kind === "import") {
    if (x.status === "preview") add("import.commit", "Провести выписку", ["finance"]);
    if (x.status === "review") add("import.resolve", "Сопоставить платёж", ["finance"]);
  }
  return a;
}

/** Prototype authorship, shown in the cabinet and the «Под капотом» console. */
export const CREDIT = {
  author: "Игорь Шварёв",
  role: "AI-разработчик (Telegram-боты, LLM)",
};
