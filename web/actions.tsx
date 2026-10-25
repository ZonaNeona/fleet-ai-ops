import { useState } from "react";
import { useForm } from "react-hook-form";
import * as Dialog from "@radix-ui/react-dialog";
import { X, Check, LoaderCircle } from "lucide-react";
import { api, Data, Row, getLabel, dirs, rub } from "./lib";
type Field = {
  key: string;
  label: string;
  type?: string;
  value?: any;
  options?: { value: string; label: string }[];
  required?: boolean;
};
export type Action = { id: string; label: string; target?: Row };
export function ActionDialog({
  action,
  data,
  onClose,
  onDone,
}: {
  action: Action;
  data: Data;
  onClose: () => void;
  onDone: (message: string, row?: Row) => void;
}) {
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [photos, setPhotos] = useState<string[]>([]);
  const { register, handleSubmit } = useForm();
  const x = action.target;
  const vehicles = data.vehicle.map((v) => ({
    value: v.id,
    label: `${v.code} · ${v.model} · ${v.status === "ready" ? "готов" : "не готов"}`,
  }));
  const clients = data.client.map((c) => ({ value: c.id, label: c.name }));
  const contracts = data.contract.map((c) => ({
    value: c.id,
    label: `${c.code} · ${getLabel(data, c.client)}`,
  }));
  const fields: Field[] = [];
  const add = (key: string, label: string, type = "text", value: any = "", options?: Field["options"]) =>
    fields.push({ key, label, type, value, options });
  const a = action.id;
  if (a === "contract.approve_terms") {
    add("rate", "Согласованная ставка / сутки, ₽", "number", x?.rate);
    add("final_payment", "Финальный выкупной платёж, ₽", "number", x?.final_payment);
    add("reason", "Основание согласования", "textarea", "Индивидуальное предложение согласовано финансистом");
  }
  if (a === "ticket.schedule") {
    add("day", "Дата визита", "date", data.today);
    add(
      "slot",
      "Сервисный интервал · время Москвы",
      "select",
      "09:00",
      ["09:00", "11:00", "13:00", "15:00", "17:00"].map((v) => ({ value: v, label: v })),
    );
  }
  if (a === "ticket.substitute") {
    add(
      "vehicle",
      "Подменный автомобиль · доступность проверит сервер",
      "select",
      vehicles.find((v) => v.value !== x?.vehicle)?.value,
      vehicles.filter((v) => v.value !== x?.vehicle),
    );
    add("end", "До какого дня", "date", new Date(Date.now() + 3 * 86400000).toISOString().slice(0, 10));
  }
  if (a === "client.create") {
    add("name", "Имя или название организации");
    add("type", "Тип", "select", "person", [
      { value: "person", label: "Физическое лицо" },
      { value: "company", label: "Организация" },
    ]);
    add("phone", "Телефон", "text", "+7 (000) 000-00-00");
    add("representative", "Представитель организации");
    add("age", "Возраст", "number", 30);
    add("experience", "Стаж, лет", "number", 5);
  }
  if (a === "client.documents")
    add(
      "documents",
      "Документы через запятую",
      "textarea",
      (x?.documents || []).join(", ") || "Паспорт, ВУ, КИС АРТ, Справка, Самозанятость",
    );
  if (a === "client.review") {
    add("approved", "Решение", "select", "true", [
      { value: "true", label: "Допустить" },
      { value: "false", label: "Отклонить" },
    ]);
    add("reason", "Основание решения", "textarea", "Комплект документов проверен сотрудником");
  }
  if (a === "contract.create") {
    add("vehicle", "Автомобиль", "select", x?.id || vehicles[0]?.value, vehicles);
    add("client", "Клиент", "select", data.session.principals[data.session.role] || clients[0]?.value, clients);
    add("start", "Дата начала", "date", data.today);
    add("end", "Дата окончания", "date", new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10));
    add(
      "schedule",
      "График",
      "select",
      "7/0",
      ["7/0", "6/1", "5/2"].map((v) => ({ value: v, label: v })),
    );
    add("final_payment", "Финальный платёж для выкупа, ₽", "number", 150000);
    add("additional_driver", "Дополнительный водитель · прокат +300 ₽/сутки");
    add("delivery", "Доставка · прокат 1500 ₽", "checkbox", false);
    add("collection", "Забор · прокат 1500 ₽", "checkbox", false);
  }
  if (a === "contract.extend") add("end", "Новая дата окончания", "date", x?.end);
  if (a === "contract.return") {
    const v = data.vehicle.find((v) => v.id === x?.vehicle);
    add("mileage", "Пробег при возврате, км", "number", v?.mileage || 0);
    add("fuel", "Топливо, %", "number", 75);
  }
  if (a === "contract.holiday") {
    add("start", "С какого дня", "date", data.today);
    add("end", "По какой день", "date", data.today);
    add("reason", "Причина", "textarea", "Заявление на согласованные выходные");
  }
  if (a === "contract.schedule")
    add(
      "schedule",
      "Новый график",
      "select",
      "5/2",
      ["7/0", "6/1", "5/2"].map((v) => ({ value: v, label: v })),
    );
  if (a === "contract.close_quote") {
    add("amount", "Утверждённая сумма досрочного выкупа, ₽", "number", 150000);
    add("reason", "Основание расчёта", "textarea", "Индивидуальный расчёт финансиста");
  }
  if (a === "contract.close") add("confirmed", "Получение платежа", "checkbox", true);
  if (a === "vehicle.inspect") {
    add("mileage", "Пробег, км", "number", x?.mileage || 0);
    add("fuel", "Топливо, %", "number", x?.fuel || 75);
    add("damage", "Повреждения", "textarea", "Новых повреждений нет");
    add("equipment", "Комплектность", "text", "Ключи, СТС, аптечка");
  }
  if (a === "vehicle.transfer")
    add(
      "branch",
      "Новая площадка",
      "select",
      x?.branch,
      data.branches.map((b) => ({ value: b.id, label: b.name })),
    );
  if (a === "ticket.create") {
    add("vehicle", "Автомобиль", "select", x?.kind === "vehicle" ? x.id : vehicles[0]?.value, vehicles);
    add("title", "Тема", "text", "Не запускается двигатель");
    add("description", "Что произошло", "textarea", "Опишите обстоятельства и необходимую помощь");
    add("priority", "Приоритет", "select", "technical", [
      { value: "urgent", label: "Срочно · 15 минут" },
      { value: "technical", label: "Техническое · 2 часа" },
      { value: "normal", label: "Обычное" },
    ]);
  }
  if (a === "ticket.estimate") {
    add("amount", "Стоимость работ, ₽", "number", Number(x?.estimate) || 8400);
    add("payer", "Кто оплачивает", "select", x?.payer || "company", [
      { value: "company", label: "Компания" },
      { value: "driver", label: "Водитель" },
      { value: "owner", label: "Владелец автомобиля" },
      { value: "insurance", label: "Страхование" },
    ]);
    add("work", "Состав работ", "textarea", "Диагностика и ремонт по результатам осмотра");
  }
  if (a === "ticket.complete") add("amount", "Фактическая стоимость, ₽", "number", x?.estimate);
  if (a === "payment.create" || a.startsWith("deposit.")) {
    add("contract", "Договор", "select", x?.id || contracts[0]?.value, contracts);
    add("amount", "Сумма, ₽", "number", a === "payment.create" ? 2500 : 20000);
    if (a !== "payment.create") add("reason", "Основание", "text", "Возврат по акту приёма");
  }
  if (a === "entry.reverse") add("reason", "Основание сторно", "textarea", "Исправление ошибочной операции");
  if (a.startsWith("period.")) add("month", "Месяц", "month", data.today.slice(0, 7));
  if (a === "owner.statement") {
    add(
      "investor",
      "Владелец",
      "select",
      x?.id || data.investor[0]?.id,
      data.investor.map((v) => ({ value: v.id, label: v.name })),
    );
    add("month", "Месяц", "month", data.today.slice(0, 7));
  }
  if (a === "referral.approve")
    add("contract", "Активный договор приглашённого", "select", contracts[0]?.value, contracts);
  if (a === "referral.create") {
    add("client", "Кто пригласил", "select", data.session.principals.driver || clients[0]?.value, clients);
    add("invited", "Приглашённый клиент", "select", clients[1]?.value, clients);
  }
  if (a === "tariff.create") {
    add("name", "Название тарифа", "text", "Новый тариф");
    add(
      "direction",
      "Направление",
      "select",
      "taxi",
      Object.entries(dirs).map(([value, label]) => ({ value, label })),
    );
    add("rate", "Ставка в сутки, ₽", "number", 2500);
    add("effective", "Действует с", "date", data.today);
  }
  if (a === "import.resolve") {
    add(
      "index",
      "Строка",
      "select",
      "0",
      (x?.unmatched || []).map((r: any, i: number) => ({
        value: String(i),
        label: `${r.reference} · ${rub(r.amount)} · ${r.error}`,
      })),
    );
    add("contract", "Сопоставить с договором", "select", contracts[0]?.value, contracts);
  }
  async function submit(values: Record<string, any>) {
    setError("");
    setPending(true);
    try {
      const payload: Record<string, any> = { ...(x ? { id: x.id, version: x.version } : {}), ...values };
      for (const f of fields) {
        if (f.type === "number") payload[f.key] = amount(values[f.key], f.label);
        if (f.type === "checkbox") payload[f.key] = !!values[f.key];
      }
      if (a === "client.documents")
        payload.documents = String(values.documents)
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean);
      if (a === "client.review") payload.approved = values.approved === "true";
      if (a === "ticket.create" || a === "contract.create") {
        delete payload.id;
        delete payload.version;
      }
      if (a === "owner.statement") {
        delete payload.id;
        delete payload.version;
      }
      if (["ticket.create", "vehicle.inspect", "contract.return"].includes(a)) payload.photos = photos;
      const row = await api("/commands", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ action: a, payload }),
      });
      onDone(action.label + " — выполнено", row);
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setPending(false);
    }
  }
  async function upload(files: FileList | null) {
    if (!files) return;
    setPending(true);
    try {
      for (const f of Array.from(files)) {
        const form = new FormData();
        form.append("file", f);
        const row = await api("/files", { method: "POST", body: form });
        setPhotos((p) => [...p, row.id]);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setPending(false);
    }
  }
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open && !pending) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="overlay" />
        <Dialog.Content className="dialog">
          <div className="dialog-top">
            <div>
              <span className="eyebrow">РАБОЧИЙ ПРОЦЕСС</span>
              <Dialog.Title>{action.label}</Dialog.Title>
            </div>
            <Dialog.Close className="icon-button" disabled={pending} aria-label="Закрыть">
              <X />
            </Dialog.Close>
          </div>
          <Dialog.Description className="muted">
            {x
              ? `${x.code} · ${x.model || x.name || x.title || "Данные вашего пространства"}`
              : "Изменения сохранятся в вашей личной демосессии."}
          </Dialog.Description>
          <form onSubmit={handleSubmit(submit)}>
            <div className="form-fields">
              {fields.map((f) => (
                <label key={f.key}>
                  {f.label}
                  {f.type === "select" ? (
                    <select {...register(f.key, { required: true })} defaultValue={f.value}>
                      {f.options?.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  ) : f.type === "textarea" ? (
                    <textarea {...register(f.key, { required: true })} defaultValue={f.value} rows={3} />
                  ) : f.type === "checkbox" ? (
                    <input type="checkbox" {...register(f.key)} defaultChecked={f.value} />
                  ) : (
                    <input
                      {...register(f.key, {
                        required: !["representative", "phone", "additional_driver"].includes(f.key),
                      })}
                      type={f.type}
                      defaultValue={f.value}
                      min={f.type === "number" ? 0 : undefined}
                    />
                  )}
                </label>
              ))}
            </div>
            {["vehicle.inspect", "ticket.create", "contract.return"].includes(a) && (
              <label className="upload">
                Фотографии · {photos.length} прикреплено
                <input type="file" multiple accept="image/png,image/jpeg" onChange={(e) => upload(e.target.files)} />
              </label>
            )}
            {!fields.length && (
              <div className="confirmation">
                <Check size={24} />
                <p>Подтвердите действие. Результат сохранится в истории и станет доступен участникам процесса.</p>
              </div>
            )}
            {error && (
              <div role="alert" className="error">
                {error}
              </div>
            )}
            <div className="dialog-actions">
              <button type="button" className="button secondary" onClick={onClose} disabled={pending}>
                Отмена
              </button>
              <button className="button primary" disabled={pending || !navigator.onLine}>
                {pending ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}Подтвердить
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** A non-negative number from a form field (the server checks again). */
function amount(v: unknown, label: string) {
  const n = Number(
    String(v ?? "")
      .replace(/\s/g, "")
      .replace(",", "."),
  );
  if (!Number.isFinite(n) || n < 0) throw new Error(`«${label}»: укажите неотрицательное число`);
  return n;
}
