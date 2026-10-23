import React, { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowUpRight,
  CalendarDays,
  CarFront,
  Check,
  CheckCircle2,
  ChevronRight,
  CreditCard,
  FileText,
  Fuel,
  Gauge,
  HelpCircle,
  LoaderCircle,
  MapPin,
  ShieldCheck,
  SlidersHorizontal,
  Upload,
  UserRound,
  Wallet,
  Wrench,
  X,
} from "lucide-react";
import { api, Data, Row, rub, dt, statuses } from "../lib";
import {
  ActionButton,
  confirmAction,
  embedded,
  getLocation,
  haptic,
  host,
  nativeApp,
  setBackButton,
  setMainButton,
  setupSdk,
} from "./sdk";
import { deepRoute } from "./route";

type MoneyState = {
  id: string;
  charged: string;
  paid: string;
  debt: string;
  deposit_paid: string;
  deposit_due: string;
  booking_state: string;
  hold_expires?: string;
  upcoming?: { date: string; amount: string; reason: string }[];
};
const statusLabel = (value?: string) => statuses[value || ""] || value || "—";
type MiniState = {
  role: string;
  onboarding_required?: boolean;
  web_cabinet?: boolean;
  contracts: MoneyState[];
  fines: Row[];
  receipts: Row[];
};
const plus = (date: string, days: number) =>
  new Date(Date.parse(date + "T12:00:00Z") + days * 86400000)
    .toISOString()
    .slice(0, 10);
const homeFor = (role: string) => (role === "driver" ? "driver" : "catalog");
const pathNow = () =>
  location.hash.startsWith("#tg/") ? location.hash.slice(4).split("&")[0] : "";
function go(path: string) {
  location.hash = "tg/" + path;
  haptic();
}
function Spinner() {
  return (
    <div className="mini-empty">
      <LoaderCircle className="mini-spin" size={27} />
      <p>Подключаем ваш кабинет…</p>
    </div>
  );
}
function ErrorBox({ text }: { text?: string }) {
  return text ? (
    <div className="mini-error" role="alert">
      {text}
    </div>
  ) : null;
}
function Empty({ title, text }: { title: string; text?: string }) {
  return (
    <div className="mini-empty">
      <CarFront size={30} />
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}

/** Retain one key for the same request after network errors, including component reloads. */
async function command(action: string, payload: Record<string, unknown>) {
  const identity = "ec-mini-command:" + action + ":" + JSON.stringify(payload);
  let key = sessionStorage.getItem(identity);
  if (!key) {
    key = crypto.randomUUID();
    sessionStorage.setItem(identity, key);
  }
  const result = await api("/commands", {
    method: "POST",
    headers: { "Idempotency-Key": key },
    body: JSON.stringify({ action, payload }),
  });
  sessionStorage.removeItem(identity);
  host("data-changed");
  haptic(true);
  return result as Row;
}
async function upload(file: File) {
  if (file.size > 8 * 1024 * 1024)
    throw new Error("Размер файла — не больше 8 МБ");
  const form = new FormData();
  form.append("file", file);
  return api<Row>("/files", { method: "POST", body: form });
}

function Primary({
  button,
  onClick,
}: {
  button: ActionButton;
  onClick: () => void;
}) {
  const callback = useRef(onClick);
  callback.current = onClick;
  useEffect(
    () => setMainButton(button, () => callback.current()),
    [button?.text, button?.busy, button?.disabled, !!button],
  );
  if (!button || nativeApp()?.initData || embedded()) return null;
  return (
    <div className="mini-action">
      <button onClick={onClick} disabled={button.disabled || button.busy}>
        {button.busy ? <LoaderCircle className="mini-spin" size={19} /> : null}
        {button.text}
      </button>
    </div>
  );
}

export function MiniApp() {
  const qc = useQueryClient();
  const auth = useQuery({
    queryKey: ["tg-auth"],
    retry: false,
    staleTime: Infinity,
    queryFn: async () => {
      await (window as any).__tg;
      const tg = nativeApp();
      if (tg?.initData)
        return api("/telegram/auth", {
          method: "POST",
          body: JSON.stringify({ initData: tg.initData }),
        });
      return api("/session");
    },
  });
  useEffect(() => {
    let cleanup: (() => void) | undefined;
    let cancelled = false;
    host("ready");
    Promise.resolve((window as any).__tg).then(() => {
      if (!cancelled) cleanup = setupSdk();
    });
    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, []);
  const boot = useQuery<Data>({
    queryKey: ["tg-bootstrap", auth.data?.id],
    queryFn: () => api("/bootstrap"),
    enabled: !!auth.data?.id,
  });
  const state = useQuery<MiniState>({
    queryKey: ["tg-state", auth.data?.id],
    queryFn: () => api("/miniapp/state"),
    enabled: !!auth.data?.id,
  });
  useEffect(() => {
    if (!auth.data?.id) return;
    const stream = new EventSource("/api/v1/events");
    let timer: ReturnType<typeof setTimeout>;
    const refresh = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["tg-bootstrap"] });
        qc.invalidateQueries({ queryKey: ["tg-state"] });
      }, 350);
    };
    stream.onmessage = refresh;
    stream.onopen = refresh;
    return () => {
      clearTimeout(timer);
      stream.close();
    };
  }, [auth.data?.id, qc]);
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    addEventListener("online", update);
    addEventListener("offline", update);
    return () => {
      removeEventListener("online", update);
      removeEventListener("offline", update);
    };
  }, []);
  const needsOnboarding =
    auth.data?.onboarding_required || state.data?.onboarding_required;
  if (
    auth.isLoading ||
    (!needsOnboarding &&
      auth.data?.id &&
      (!boot.data || !state.data) &&
      !boot.error &&
      !state.error)
  )
    return (
      <div className="mini">
        <Spinner />
      </div>
    );
  if (needsOnboarding)
    return (
      <div className="mini">
        <div className="mini-welcome">
          <ShieldCheck size={38} />
          <span className="mini-eyebrow">ТАКСОПАРК · ВАШ КАБИНЕТ</span>
          <h1>Начнём со знакомства</h1>
          <p>
            В боте подтвердите согласие, поделитесь номером и выберите демороль.
            После этого здесь появятся ваши автомобили и документы.
          </p>
          {embedded() ? (
            <button className="mini-primary" onClick={() => host("close")}>
              Продолжить в чате
            </button>
          ) : (
            <a
              className="mini-primary"
              href={`https://t.me/${auth.data?.telegram_username || boot.data?.telegram_username || ""}?start=onboarding`}
            >
              Продолжить в боте <ArrowUpRight size={17} />
            </a>
          )}
          <button
            className="mini-link"
            onClick={() => {
              qc.invalidateQueries({ queryKey: ["tg-auth"] });
              qc.invalidateQueries({ queryKey: ["tg-state"] });
            }}
          >
            Я прошёл онбординг · обновить
          </button>
          <small>Концепт и прототип · учебные данные</small>
        </div>
      </div>
    );
  if (auth.error || boot.error || state.error || !boot.data || !state.data)
    return (
      <div className="mini">
        <Empty
          title="Не удалось открыть кабинет"
          text={
            (auth.error || boot.error || state.error)?.message ||
            "Начните личную демосессию на сайте."
          }
        />
        <button className="mini-primary" onClick={() => qc.invalidateQueries()}>
          Повторить
        </button>
        <a className="mini-link" href="/">
          На сайт проекта
        </a>
      </div>
    );
  if (state.data.web_cabinet)
    return (
      <div className="mini">
        <div className="mini-welcome">
          <CarFront size={36} />
          <h1>
            {boot.data.session.role === "owner"
              ? "Ваш бизнес. Вся картина."
              : "Рабочее место отдела"}
          </h1>
          <p>
            {boot.data.session.role === "owner"
              ? "Экономика, загрузка и решения — в мобильном дашборде."
              : "В демо доступно в веб-кабинете."}
          </p>
          <a
            className="mini-primary"
            href="/?web=1"
            target={embedded() ? "_top" : "_self"}
          >
            Открыть{" "}
            {boot.data.session.role === "owner" ? "дашборд" : "веб-кабинет"}
            <ArrowUpRight size={17} />
          </a>
        </div>
      </div>
    );
  return (
    <Experience
      key={boot.data.session.id + boot.data.session.role}
      data={boot.data}
      state={state.data}
      online={online}
      refresh={async () => {
        await Promise.all([
          qc.invalidateQueries({ queryKey: ["tg-bootstrap"] }),
          qc.invalidateQueries({ queryKey: ["tg-state"] }),
        ]);
      }}
    />
  );
}

function Experience({
  data,
  state,
  online,
  refresh,
}: {
  data: Data;
  state: MiniState;
  online: boolean;
  refresh: () => Promise<void>;
}) {
  const home = homeFor(data.session.role);
  const [path, setPath] = useState(
    pathNow() || deepRoute(nativeApp()?.initDataUnsafe?.start_param) || home,
  );
  const [payment, setPayment] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    if (!location.hash.startsWith("#tg/"))
      history.replaceState(
        null,
        "",
        location.pathname + location.search + "#tg/" + path,
      );
    const follow = () => {
      setPath(pathNow() || home);
      setError("");
      setNotice("");
      setPayment(null);
    };
    addEventListener("hashchange", follow);
    return () => removeEventListener("hashchange", follow);
  }, [home]);
  const back = () => {
    if (payment) setPayment(null);
    else
      go(
        path.startsWith("driver")
          ? "driver"
          : path.startsWith("rentals/")
            ? "rentals"
            : home,
      );
  };
  useEffect(
    () => setBackButton(path !== home || !!payment, back),
    [path, home, !!payment],
  );
  async function run(fn: () => Promise<unknown>, message?: string) {
    if (!online || busy) return;
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
      if (message) setNotice(message);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function pay(purpose: string, target: string) {
    await run(async () =>
      setPayment(await command("demo_payment.create", { purpose, target })),
    );
  }
  const isDriver = data.session.role === "driver";
  const tabs = isDriver
    ? ([
        ["driver", "Главная", CarFront],
        ["driver/fines", "Штрафы", ShieldCheck],
        ["driver/help", "Помощь", HelpCircle],
        ["profile", "Профиль", UserRound],
      ] as const)
    : ([
        ["catalog", "Каталог", CarFront],
        ["rentals", "Мои аренды", CalendarDays],
        ["profile", "Профиль", UserRound],
      ] as const);
  const money = (id: string) => state.contracts.find((c) => c.id === id);
  const vehicle = (id: string) => data.vehicle.find((v) => v.id === id);
  const selectedContract = path.startsWith("rentals/")
    ? data.contract.find((c) => c.id === path.split("/")[1])
    : null;
  const active = data.contract.filter((c) => c.status === "active");
  const my = active[0];
  const myCar = my && vehicle(my.vehicle);
  const selectedTicket = path.startsWith("driver/tickets/")
    ? data.ticket.find((t) => t.id === path.split("/")[2])
    : null;
  const isCatalog =
    !isDriver && (path === "catalog" || path.startsWith("car/"));
  return (
    <div className="mini">
      <header className="mini-header">
        <button
          aria-label="Назад"
          className="mini-icon"
          onClick={back}
          disabled={path === home && !payment}
        >
          <ArrowLeft size={19} />
        </button>
        <div className="mini-brand">
          ТАКСО<span>ПАРК</span>
          <small>{isDriver ? "DRIVER EXPERIENCE" : "RENTAL EXPERIENCE"}</small>
        </div>
        <span className="mini-demo">ДЕМО</span>
      </header>
      {!online && (
        <div className="mini-offline" role="status">
          Нет сети. Изменения станут доступны после подключения.
        </div>
      )}
      <main className="mini-content">
        <ErrorBox text={error} />
        {notice && (
          <div className="mini-success" role="status">
            <CheckCircle2 size={18} />
            {notice}
          </div>
        )}
        {payment ? (
          <section className="mini-pay">
            <span className="mini-circle">
              <CreditCard size={27} />
            </span>
            <span className="mini-eyebrow">ТЕСТОВЫЙ РЕЖИМ</span>
            <h1>
              {payment.status === "paid" ? "Оплата проведена" : payment.label}
            </h1>
            <div className="mini-big-amount">{rub(payment.amount)}</div>
            <p>
              {payment.status === "paid"
                ? "Операция появилась в учёте. Баланс обновлён."
                : "Деньги с карты не списываются. Учебная операция появится в финансовом журнале."}
            </p>
            <div className="mini-receipt">
              <span>Квитанция</span>
              <strong>{payment.code}</strong>
              <span>Способ оплаты</span>
              <strong>Демонстрационный</strong>
            </div>
            {payment.status === "paid" ? (
              <>
                <a
                  className="mini-primary"
                  href={`/api/v1/miniapp/receipts/${payment.id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <FileText size={18} /> Скачать квитанцию
                </a>
                <button className="mini-link" onClick={() => setPayment(null)}>
                  Вернуться в кабинет
                </button>
              </>
            ) : (
              <Primary
                button={{
                  text: `Подтвердить учебную оплату · ${rub(payment.amount)}`,
                  disabled: !online,
                  busy,
                }}
                onClick={() =>
                  run(async () =>
                    setPayment(
                      await command("demo_payment.confirm", { id: payment.id }),
                    ),
                  )
                }
              />
            )}
          </section>
        ) : (
          <>
            {isCatalog && (
              <Catalog
                data={data}
                path={path}
                online={online}
                refresh={refresh}
              />
            )}
            {!isDriver && path === "rentals" && (
              <>
                <div className="mini-title">
                  <span className="mini-eyebrow">ВАШИ ПОЕЗДКИ</span>
                  <h1>Мои аренды</h1>
                  <p>От первого резерва до возвращения ключей.</p>
                </div>
                {[...data.contract].reverse().map((c) => (
                  <button
                    className="mini-rental"
                    key={c.id}
                    onClick={() => go("rentals/" + c.id)}
                  >
                    <img src={vehicle(c.vehicle)?.image} alt="" />
                    <div>
                      <span className={"mini-badge " + c.status}>
                        {statusLabel(c.status)}
                      </span>
                      <h3>{vehicle(c.vehicle)?.model}</h3>
                      <p>
                        {dt(c.start)} — {dt(c.end)}
                      </p>
                      <small>{c.code}</small>
                    </div>
                    <ChevronRight size={18} />
                  </button>
                ))}
                {!data.contract.length && (
                  <Empty
                    title="Здесь начнётся ваша история"
                    text="Выберите автомобиль в каталоге — первая бронь появится здесь."
                  />
                )}
              </>
            )}
            {path.startsWith("rentals/") &&
              (selectedContract ? (
                <Rental
                  c={selectedContract}
                  car={vehicle(selectedContract.vehicle)}
                  amounts={money(selectedContract.id)}
                  pay={() => pay("deposit", selectedContract.id)}
                  cancel={() =>
                    run(
                      () =>
                        command("contract.cancel", { id: selectedContract.id }),
                      "Бронь отменена. Если залог внесён, запрос возврата передан финансисту.",
                    )
                  }
                  busy={busy || !online}
                />
              ) : (
                <Empty
                  title="Аренда недоступна"
                  text="Проверьте роль и выбранную демосессию."
                />
              ))}
            {isDriver && path === "driver" && (
              <>
                <div className="mini-title">
                  <span className="mini-eyebrow">ХОРОШЕЙ СМЕНЫ</span>
                  <h1>
                    {data.client
                      .find((c) => c.id === data.session.principals.driver)
                      ?.name?.split(" ")[0] || "Ваш кабинет"}
                  </h1>
                  <p>Автомобиль, расчёты и помощь — рядом.</p>
                </div>
                <section className="mini-balance">
                  <span>К оплате по действующим договорам</span>
                  <strong>
                    {rub(
                      active.reduce(
                        (a, c) => a + Number(money(c.id)?.debt || 0),
                        0,
                      ),
                    )}
                  </strong>
                  <small>Залоги и штрафы считаются отдельно</small>
                </section>
                {active.map((c) => (
                  <div className="mini-surface" key={c.id}>
                    <div className="mini-row">
                      <strong>{vehicle(c.vehicle)?.model}</strong>
                      <span>{c.code}</span>
                    </div>
                    <div className="mini-numbers">
                      <div>
                        <small>Начислено</small>
                        <b>{rub(money(c.id)?.charged)}</b>
                      </div>
                      <div>
                        <small>Оплачено</small>
                        <b>{rub(money(c.id)?.paid)}</b>
                      </div>
                    </div>
                    {Number(money(c.id)?.debt) > 0 && (
                      <button
                        className="mini-primary"
                        disabled={busy || !online}
                        onClick={() => pay("rent", c.id)}
                      >
                        Оплатить · {rub(money(c.id)?.debt)}
                      </button>
                    )}
                    <a
                      className="mini-link"
                      href={`/api/v1/documents/${c.id}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Договор PDF <ArrowUpRight size={14} />
                    </a>
                  </div>
                ))}
                {my && !!money(my.id)?.upcoming?.length && (
                  <section className="mini-surface">
                    <h3>Ближайшие начисления</h3>
                    <div className="mini-receipt">
                      {money(my.id)!.upcoming!.map((day) => (
                        <React.Fragment key={day.date}>
                          <span>
                            {dt(day.date)}
                            <small style={{ display: "block" }}>
                              {day.reason}
                            </small>
                          </span>
                          <b>{rub(day.amount)}</b>
                        </React.Fragment>
                      ))}
                    </div>
                    <p className="mini-hint">
                      По утверждённому графику договора {my.code}.
                    </p>
                  </section>
                )}
                {myCar && (
                  <div className="mini-own-car">
                    <img src={myCar.image} alt={myCar.model} />
                    <div>
                      <span className="mini-eyebrow">ВАШ АВТОМОБИЛЬ</span>
                      <h2>{myCar.model}</h2>
                      <p>
                        {myCar.plate} · {myCar.code}
                      </p>
                      <div className="mini-specs">
                        <span>
                          <Gauge size={15} />
                          {Number(myCar.mileage).toLocaleString("ru")} км
                        </span>
                        <span>
                          <Fuel size={15} />
                          {myCar.fuel}%
                        </span>
                      </div>
                    </div>
                  </div>
                )}
                <button
                  className="mini-shortcut"
                  onClick={() => go("driver/inspection")}
                >
                  <ShieldCheck />
                  <div>
                    <strong>Предсменный осмотр</strong>
                    <small>Четыре фото — и всё зафиксировано</small>
                  </div>
                  <ChevronRight size={17} />
                </button>
              </>
            )}
            {isDriver && path.startsWith("driver/fines") && (
              <>
                <div className="mini-title">
                  <span className="mini-eyebrow">СВЕРКА ЧЕРЕЗ N8N</span>
                  <h1>Штрафы</h1>
                  <p>
                    Учебные постановления. Оплата отражается отдельно от аренды.
                  </p>
                </div>
                <button
                  className="mini-link"
                  disabled={busy || !online}
                  onClick={() =>
                    run(async () => {
                      await api("/miniapp/fines/sync", {
                        method: "POST",
                        body: "{}",
                      });
                    }, "Запрос отправлен в n8n. Список обновится после синхронизации.")
                  }
                >
                  Обновить из источника
                </button>
                {state.fines
                  .filter(
                    (f) =>
                      path === "driver/fines" || f.id === path.split("/")[2],
                  )
                  .map((f) => (
                    <div className="mini-surface" key={f.id}>
                      <div className="mini-row">
                        <span
                          className={
                            "mini-badge " +
                            (f.status === "paid" ? "completed" : "draft")
                          }
                        >
                          {f.status === "paid" ? "Оплачено" : "К оплате"}
                        </span>
                        <small>{vehicle(f.vehicle)?.plate}</small>
                      </div>
                      <h2>{rub(f.due)}</h2>
                      <p>{f.external_id}</p>
                      {f.discount_percent > 0 && (
                        <p className="mini-hint">
                          Учебная скидка {f.discount_percent}% до{" "}
                          {dt(f.discount_until)} · исходная сумма{" "}
                          {rub(f.amount)}
                        </p>
                      )}
                      <small>
                        {f.source} · {f.at ? dt(f.at) : ""}
                      </small>
                      {f.status !== "paid" ? (
                        <button
                          className="mini-primary"
                          disabled={busy || !online}
                          onClick={() => pay("fine", f.id)}
                        >
                          Оплатить {f.discount_percent ? "со скидкой" : ""} ·{" "}
                          {rub(f.due)}
                        </button>
                      ) : (
                        <a
                          className="mini-link"
                          href={`/api/v1/miniapp/receipts/${f.receipt}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Квитанция PDF
                        </a>
                      )}
                    </div>
                  ))}
                {!state.fines.length && (
                  <Empty
                    title="Постановлений пока нет"
                    text="Запросите свежую сверку через n8n."
                  />
                )}
              </>
            )}
            {isDriver && path === "driver/help" && (
              <>
                <div className="mini-title">
                  <span className="mini-eyebrow">МЫ РЯДОМ</span>
                  <h1>Помощь на дороге</h1>
                  <p>Зафиксируйте ситуацию — отдел получит всё необходимое.</p>
                </div>
                <button
                  className="mini-shortcut"
                  onClick={() => go("driver/accident")}
                >
                  <HelpCircle />
                  <div>
                    <strong>Сообщить о ДТП</strong>
                    <small>Место, обстоятельства и фотографии</small>
                  </div>
                  <ChevronRight />
                </button>
                <button
                  className="mini-shortcut"
                  onClick={() => go("driver/inspection")}
                >
                  <ShieldCheck />
                  <div>
                    <strong>Осмотреть автомобиль</strong>
                    <small>Пробег, топливо, замечания</small>
                  </div>
                  <ChevronRight />
                </button>
                <h2>Мои обращения</h2>
                {data.ticket.map((t) => (
                  <button
                    className="mini-shortcut"
                    key={t.id}
                    onClick={() => go("driver/tickets/" + t.id)}
                  >
                    <Wrench size={19} />
                    <div>
                      <strong>{t.title}</strong>
                      <small>
                        {t.code} · {statusLabel(t.status)}
                      </small>
                    </div>
                    <ChevronRight size={16} />
                  </button>
                ))}
              </>
            )}
            {isDriver &&
              (path === "driver/accident" || path === "driver/inspection") && (
                <DriverForm
                  key={path}
                  inspection={path.endsWith("inspection")}
                  cars={
                    active
                      .map((c) => vehicle(c.vehicle))
                      .filter(Boolean) as Row[]
                  }
                  online={online}
                  onDone={async (row) => {
                    await refresh();
                    go(
                      row.kind === "ticket"
                        ? "driver/tickets/" + row.id
                        : "driver",
                    );
                    setNotice(
                      row.kind === "ticket"
                        ? "Обращение передано техническому отделу"
                        : "Осмотр сохранён. Спасибо за внимательность.",
                    );
                  }}
                />
              )}
            {isDriver &&
              path.startsWith("driver/tickets/") &&
              (selectedTicket ? (
                <div className="mini-surface">
                  <span className="mini-badge">
                    {statusLabel(selectedTicket.status)}
                  </span>
                  <h1>{selectedTicket.title}</h1>
                  <p>{selectedTicket.description}</p>
                  {selectedTicket.location && (
                    <p>
                      <MapPin size={15} /> {selectedTicket.location}
                    </p>
                  )}
                  <div className="mini-receipt">
                    <span>Номер</span>
                    <b>{selectedTicket.code}</b>
                    <span>Ответственный</span>
                    <b>{selectedTicket.assignee}</b>
                    <span>Срок реакции</span>
                    <b>
                      {new Date(selectedTicket.due).toLocaleString("ru-RU", {
                        timeZone: "Europe/Moscow",
                      })}{" "}
                      МСК
                    </b>
                  </div>
                  {selectedTicket.photos?.map((id: string) => (
                    <a
                      className="mini-link"
                      key={id}
                      href={`/api/v1/files/${id}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Фото к обращению <ArrowUpRight size={14} />
                    </a>
                  ))}
                </div>
              ) : (
                <Empty title="Обращение недоступно" />
              ))}
            {path === "profile" && (
              <Profile
                data={data}
                state={state}
                online={online}
                refresh={refresh}
              />
            )}
          </>
        )}
        <footer className="mini-credit">
          Концепт и прототип · учебные данные
          <br />
          Игорь Шварёв ·{" "}
          <a href="/credits.html" target="_blank" rel="noreferrer">
            Фото и авторство
          </a>
        </footer>
      </main>
      {!payment && (
        <nav className="mini-nav" aria-label="Разделы кабинета">
          {tabs.map(([id, label, Icon]) => (
            <button
              key={id}
              aria-current={path === id ? "page" : undefined}
              className={
                path === id || (id === "rentals" && path.startsWith("rentals/"))
                  ? "active"
                  : ""
              }
              onClick={() => go(id)}
            >
              <Icon size={20} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
      )}
    </div>
  );
}

function Catalog({
  data,
  path,
  online,
  refresh,
}: {
  data: Data;
  path: string;
  online: boolean;
  refresh: () => Promise<void>;
}) {
  const [start, setStart] = useState(plus(data.today, 1));
  const [end, setEnd] = useState(plus(data.today, 4));
  const [carClass, setClass] = useState("");
  const [price, setPrice] = useState(0);
  const [driver, setDriver] = useState("");
  const [delivery, setDelivery] = useState(false);
  const [collection, setCollection] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const car = path.startsWith("car/")
    ? data.vehicle.find((v) => v.id === path.split("/")[1])
    : undefined;
  const available = useQuery({
    queryKey: ["tg-availability", start, end, data.session.id],
    queryFn: () => api(`/availability?start=${start}&end=${end}`),
    enabled: end > start && start >= data.today,
  });
  const payload = {
    vehicle: car?.id,
    start,
    end,
    additional_driver: driver,
    delivery,
    collection,
  };
  const quote = useQuery({
    queryKey: ["tg-quote", payload, data.session.id],
    queryFn: () =>
      api("/rental/quote", { method: "POST", body: JSON.stringify(payload) }),
    enabled: !!car && start >= data.today && end > start,
    staleTime: 0,
    retry: false,
  });
  const eligible = new Set(
    (available.data?.items || [])
      .filter((v: any) => v.available)
      .map((v: any) => v.id),
  );
  const cars = data.vehicle.filter(
    (v) =>
      ["rental", "commercial"].includes(v.direction) &&
      eligible.has(v.id) &&
      (!carClass || v.class === carClass) &&
      (!price || Number(v.rate) <= price),
  );
  const classes = [
    ...new Set(
      data.vehicle
        .filter((v) => ["rental", "commercial"].includes(v.direction))
        .map((v) => String(v.class)),
    ),
  ];
  const changeStart = (v: string) => {
    setStart(v);
    if (end <= v) setEnd(plus(v, 3));
  };
  const ready =
    !!car &&
    !!quote.data &&
    !quote.isFetching &&
    !quote.isError &&
    !available.isFetching &&
    !available.isError &&
    eligible.has(car.id) &&
    end > start;
  async function book() {
    if (!ready || !online || busy) return;
    setBusy(true);
    setError("");
    try {
      const c = await command("contract.create", {
        ...payload,
        quote_version: quote.data.version,
      });
      await refresh();
      go("rentals/" + c.id);
    } catch (e: any) {
      setError(e.message);
      quote.refetch();
      available.refetch();
    } finally {
      setBusy(false);
    }
  }
  const dates = (
    <section className="mini-dates">
      <div className="mini-date-grid">
        <label>
          <span>Получение · 10:00 МСК</span>
          <input
            aria-label="Дата получения"
            type="date"
            min={data.today}
            value={start}
            onChange={(e) => changeStart(e.target.value)}
          />
        </label>
        <span className="mini-date-arrow">→</span>
        <label>
          <span>Возврат · 10:00 МСК</span>
          <input
            aria-label="Дата возврата"
            type="date"
            min={plus(start || data.today, 1)}
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </label>
      </div>
      <div className="mini-chips">
        {[3, 7, 30].map((n) => (
          <button
            key={n}
            className={end === plus(start || data.today, n) ? "selected" : ""}
            onClick={() => setEnd(plus(start || data.today, n))}
          >
            {n} {n === 3 ? "дня" : "дней"}
            {n > 3 && <small>−{n === 7 ? 5 : 10}%</small>}
          </button>
        ))}
      </div>
    </section>
  );
  if (car)
    return (
      <>
        <div className="mini-gallery">
          {[...new Set<string>(car.images?.length ? car.images : [car.image])]
            .filter(Boolean)
            .map((src, i) => (
              <img key={src} src={src} alt={`${car.model} · фото ${i + 1}`} />
            ))}
          <span className="mini-gallery-tag">
            {car.class} · {car.year}
          </span>
        </div>
        <div className="mini-title">
          <span className="mini-eyebrow">СВОБОДА В КАЖДОЙ ПОЕЗДКЕ</span>
          <h1>{car.model}</h1>
          <div className="mini-specs">
            <span>
              <Gauge size={15} />
              250 км / сутки
            </span>
            <span>
              <ShieldCheck size={15} />
              Осмотр перед выдачей
            </span>
          </div>
        </div>
        {dates}
        <div className="mini-surface">
          <h3>Сделаем поездку удобнее</h3>
          <label className="mini-check">
            <input
              type="checkbox"
              checked={delivery}
              onChange={(e) => setDelivery(e.target.checked)}
            />
            <span>
              Доставка автомобиля<small>1 500 ₽</small>
            </span>
          </label>
          <label className="mini-check">
            <input
              type="checkbox"
              checked={collection}
              onChange={(e) => setCollection(e.target.checked)}
            />
            <span>
              Забрать после аренды<small>1 500 ₽</small>
            </span>
          </label>
          <label className="mini-field">
            Дополнительный водитель · 300 ₽ / сутки
            <input
              placeholder="Имя, если нужен"
              value={driver}
              onChange={(e) => setDriver(e.target.value)}
              maxLength={120}
            />
          </label>
        </div>
        <div className="mini-surface">
          <h3>Прозрачный расчёт</h3>
          {quote.data ? (
            <div className="mini-receipt">
              <span>Аренда · {quote.data.days} сут.</span>
              <b>{rub(quote.data.rental_total)}</b>
              {quote.data.discount_percent > 0 && (
                <>
                  <span>Скидка за срок</span>
                  <b className="mini-positive">
                    −{quote.data.discount_percent}%
                  </b>
                </>
              )}
              <span>Доставка и забор</span>
              <b>{rub(quote.data.services_amount)}</b>
              <span className="mini-total">Стоимость аренды</span>
              <b className="mini-total">{rub(quote.data.total)}</b>
              <span>Возвратный залог отдельно</span>
              <b>{rub(quote.data.deposit)}</b>
            </div>
          ) : (
            <p>Рассчитываем стоимость…</p>
          )}
          <p className="mini-hint">
            Резерв на 30 минут. Менеджер подтвердит бронь после проверки
            документов. Бронирование не списывает деньги.
          </p>
          {!eligible.has(car.id) && available.data && (
            <ErrorBox text="На эти даты автомобиль недоступен. Выберите другой период." />
          )}
        </div>
        <ErrorBox
          text={error || quote.error?.message || available.error?.message}
        />
        <Primary
          button={{
            text: quote.data
              ? `Забронировать за ${rub(quote.data.total)}`
              : "Рассчитываем стоимость…",
            disabled: !ready || !online,
            busy,
          }}
          onClick={book}
        />
      </>
    );
  return (
    <>
      <div className="mini-title">
        <span className="mini-eyebrow">КЛЮЧИ К ВАШИМ ПЛАНАМ</span>
        <h1>
          Поездка начинается
          <br />
          <em>с правильного авто.</em>
        </h1>
        <p>На выходные, в путешествие или по делам.</p>
      </div>
      {dates}
      <div className="mini-filter">
        <div className="mini-chips">
          <button
            className={!carClass ? "selected" : ""}
            onClick={() => setClass("")}
          >
            Все
          </button>
          {classes.map((c) => (
            <button
              key={c}
              className={c === carClass ? "selected" : ""}
              onClick={() => setClass(c)}
            >
              {c}
            </button>
          ))}
        </div>
        <label>
          <SlidersHorizontal size={15} />
          <select
            aria-label="Цена в сутки"
            value={price}
            onChange={(e) => setPrice(Number(e.target.value))}
          >
            <option value={0}>Любая цена</option>
            <option value={3500}>До 3 500 ₽ / сутки</option>
            <option value={6000}>До 6 000 ₽ / сутки</option>
          </select>
        </label>
      </div>
      <div className="mini-row mini-catalog-count">
        <h2>Выберите свой автомобиль</h2>
        <span>{available.isFetching ? "…" : cars.length}</span>
      </div>
      <ErrorBox
        text={
          available.error?.message ||
          (end <= start ? "Возврат должен быть позже получения" : "")
        }
      />
      {available.isLoading ? (
        <Spinner />
      ) : cars.length ? (
        cars.map((v, i) => (
          <button
            className="mini-car"
            key={v.id}
            onClick={() => go("car/" + v.id)}
          >
            <div className="mini-car-image">
              <img
                src={v.image}
                alt={v.model}
                loading={i < 2 ? "eager" : "lazy"}
              />
              <span className="mini-car-class">{v.class}</span>
              <span className="mini-car-arrow">
                <ArrowUpRight size={22} />
              </span>
            </div>
            <div className="mini-car-info">
              <div>
                <h2>{v.model}</h2>
                <p>
                  {v.year} ·{" "}
                  {v.direction === "commercial"
                    ? "Для бизнеса"
                    : "Для ваших маршрутов"}
                </p>
              </div>
              <div className="mini-car-rate">
                <b>{rub(v.rate)}</b>
                <small>базовая ставка / сутки</small>
              </div>
            </div>
          </button>
        ))
      ) : (
        <Empty
          title="На эти даты всё занято"
          text="Измените даты или снимите фильтры — подберём другой вариант."
        />
      )}
    </>
  );
}

function Rental({
  c,
  car,
  amounts,
  pay,
  cancel,
  busy,
}: {
  c: Row;
  car?: Row;
  amounts?: MoneyState;
  pay: () => void;
  cancel: () => void;
  busy: boolean;
}) {
  const [tick, setTick] = useState(Date.now());
  const [confirmCancel, setConfirmCancel] = useState(false);
  useEffect(() => {
    const t = setInterval(() => setTick(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const remaining = amounts?.hold_expires
    ? Math.max(0, Math.floor((Date.parse(amounts.hold_expires) - tick) / 1000))
    : 0;
  const stages = ["draft", "confirmed", "active", "completed"];
  const index = stages.indexOf(c.status);
  return (
    <>
      <div className="mini-title">
        <span className="mini-eyebrow">ВАША АРЕНДА · {c.code}</span>
        <h1>{car?.model}</h1>
        <span className={"mini-badge " + c.status}>
          {c.status === "draft"
            ? remaining
              ? "Резерв · ждёт менеджера"
              : "Резерв истёк"
            : statusLabel(c.status)}
        </span>
      </div>
      {car?.image && (
        <img className="mini-rental-hero" src={car.image} alt={car.model} />
      )}
      <section className="mini-surface">
        <div className="mini-row">
          <span>
            {dt(c.start)} → {dt(c.end)}
          </span>
          <b>10:00 МСК</b>
        </div>
        {c.status === "draft" && (
          <p className="mini-hint">
            {remaining
              ? `Резерв сохраняется ещё ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}. Менеджер проверит документы и подтвердит бронь.`
              : "Создайте новую бронь с актуальной доступностью."}
          </p>
        )}
        <div className="mini-timeline">
          {["Заявка", "Подтверждение", "Выдача", "Возврат"].map((text, i) => (
            <div key={text} className={i <= index ? "done" : ""}>
              <span>{i <= index ? <Check size={13} /> : i + 1}</span>
              <small>{text}</small>
            </div>
          ))}
        </div>
        <div className="mini-receipt">
          <span>Стоимость аренды</span>
          <b>
            {rub(
              c.quote_total ||
                Number(c.rate) *
                  Math.max(
                    1,
                    (Date.parse(c.end) - Date.parse(c.start)) / 86400000,
                  ) +
                  Number(c.services_amount || 0),
            )}
          </b>
          <span>Возвратный залог</span>
          <b>{rub(c.deposit)}</b>
          <span>Залог получен</span>
          <b>{rub(amounts?.deposit_paid)}</b>
        </div>
        {c.refund_status && (
          <p className="mini-hint">
            Возврат залога:{" "}
            {c.refund_status === "completed"
              ? "выполнен"
              : "ожидает финансиста"}
          </p>
        )}
        {["confirmed", "active"].includes(c.status) &&
          Number(amounts?.deposit_due) > 0 && (
            <button className="mini-primary" onClick={pay} disabled={busy}>
              Оплатить залог · {rub(amounts?.deposit_due)}
            </button>
          )}
        <a
          className="mini-link"
          href={`/api/v1/documents/${c.id}`}
          target="_blank"
          rel="noreferrer"
        >
          <FileText size={16} /> Договор и расчёты PDF
        </a>
        <button className="mini-link" onClick={() => go("profile")}>
          Документы для проверки <ChevronRight size={15} />
        </button>
        {["draft", "confirmed"].includes(c.status) &&
          (confirmCancel ? (
            <div className="mini-cancel">
              <p>
                Отменить бронирование? Возврат внесённого залога подтвердит
                финансист.
              </p>
              <button className="mini-primary" disabled={busy} onClick={cancel}>
                Да, отменить бронь
              </button>
              <button
                className="mini-link"
                onClick={() => setConfirmCancel(false)}
              >
                Сохранить бронь
              </button>
            </div>
          ) : (
            <button
              className="mini-link mini-danger"
              onClick={() =>
                confirmAction(
                  "Отменить бронь? Если залог внесён, запрос возврата получит финансист.",
                  cancel,
                  () => setConfirmCancel(true),
                )
              }
            >
              Отменить бронирование
            </button>
          ))}
      </section>
    </>
  );
}

function Profile({
  data,
  state,
  online,
  refresh,
}: {
  data: Data;
  state: MiniState;
  online: boolean;
  refresh: () => Promise<void>;
}) {
  const person = data.client.find(
    (c) => c.id === data.session.principals[data.session.role],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function attach(type: string, file?: File) {
    if (!file || !person || !online) return;
    setBusy(true);
    setError("");
    try {
      const f = await upload(file);
      const document_files = [
        ...(person.document_files || []).filter((d: any) => d.type !== type),
        { type, file: f.id },
      ];
      await command("client.documents", { id: person.id, document_files });
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="mini-title">
        <span className="mini-eyebrow">ЛИЧНОЕ ПРОСТРАНСТВО</span>
        <h1>{person?.name || "Ваш профиль"}</h1>
        <p>
          {data.session.role === "driver" ? "Водитель" : "Клиент проката"} ·
          учебная карточка
        </p>
      </div>
      <ErrorBox text={error} />
      <section className="mini-surface">
        <div className="mini-row">
          <h2>Документы</h2>
          <span className="mini-badge">{statusLabel(person?.status)}</span>
        </div>
        <p className="mini-hint">
          Для демонстрации используйте учебные изображения. JPEG, PNG или PDF,
          до 8 МБ.
        </p>
        {[
          ["passport", "Паспорт"],
          ["license", "Водительское удостоверение"],
        ].map(([type, title]) => {
          const doc = person?.document_files?.find((d: any) => d.type === type);
          return (
            <div className="mini-document" key={type}>
              <FileText size={23} />
              <div>
                <strong>{title}</strong>
                <small>{doc ? doc.name : "Файл ещё не загружен"}</small>
                {doc && (
                  <a
                    href={`/api/v1/files/${doc.file}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Открыть
                  </a>
                )}
              </div>
              <label className="mini-upload">
                <Upload size={18} />
                <input
                  aria-label={`Загрузить: ${title}`}
                  type="file"
                  accept="image/jpeg,image/png,application/pdf"
                  disabled={busy || !online}
                  onChange={(e) => attach(type, e.target.files?.[0])}
                />
              </label>
            </div>
          );
        })}
        {busy && <p className="mini-hint">Загружаем документ…</p>}
        <p className="mini-hint">
          Загрузка передаёт комплект сотруднику на проверку. Решение принимает
          специалист.
        </p>
      </section>
      <section className="mini-surface">
        <h2>Квитанции</h2>
        {state.receipts
          .filter((r) => r.status === "paid")
          .map((r) => (
            <a
              key={r.id}
              className="mini-shortcut"
              href={`/api/v1/miniapp/receipts/${r.id}`}
              target="_blank"
              rel="noreferrer"
            >
              <FileText size={19} />
              <div>
                <strong>
                  {rub(r.amount)} · {r.code}
                </strong>
                <small>{r.label}</small>
              </div>
              <ArrowUpRight size={16} />
            </a>
          ))}
        {!state.receipts.some((r) => r.status === "paid") && (
          <p className="mini-hint">Здесь появятся квитанции учебных оплат.</p>
        )}
      </section>
      <div className="mini-surface">
        <ShieldCheck size={22} />
        <h3>Ваши данные под контролем</h3>
        <p>
          Согласие и сведения о хранении доступны в боте через /privacy. Отзыв
          согласия — /delete_me.
        </p>
      </div>
    </>
  );
}

function DriverForm({
  inspection,
  cars,
  online,
  onDone,
}: {
  inspection: boolean;
  cars: Row[];
  online: boolean;
  onDone: (row: Row) => Promise<void>;
}) {
  const [vehicle, setVehicle] = useState(cars[0]?.id || "");
  const car = cars.find((v) => v.id === vehicle);
  const [step, setStep] = useState(0);
  const [location, setLocation] = useState("");
  const [notes, setNotes] = useState("");
  const [shots, setShots] = useState<Record<string, Row>>({});
  const [mileage, setMileage] = useState(String(car?.mileage || 0));
  const [fuel, setFuel] = useState(String(car?.fuel || 0));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const positions = inspection
    ? [
        ["front", "Спереди"],
        ["rear", "Сзади"],
        ["left", "Слева"],
        ["right", "Справа"],
      ]
    : [
        ["scene", "Общий план"],
        ["damage", "Повреждения"],
      ];
  async function photo(key: string, file?: File) {
    if (!file || busy) return;
    setBusy(true);
    setError("");
    try {
      const f = await upload(file);
      setShots((s) => ({ ...s, [key]: f }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const valid = inspection
    ? Object.keys(shots).length === 4 &&
      Number(mileage) >= Number(car?.mileage) &&
      Number(fuel) >= 0 &&
      Number(fuel) <= 100
    : !!location.trim() && !!notes.trim() && Object.keys(shots).length > 0;
  async function submit() {
    if (!valid || busy || !online) return;
    setBusy(true);
    setError("");
    try {
      const row = await command(
        inspection ? "driver.inspection" : "ticket.create",
        inspection
          ? {
              vehicle,
              mileage: Number(mileage),
              fuel: Number(fuel),
              notes,
              shots: Object.fromEntries(
                Object.entries(shots).map(([k, f]) => [k, f.id]),
              ),
            }
          : {
              vehicle,
              title: "ДТП · обращение водителя",
              description: notes,
              location,
              photos: Object.values(shots).map((f) => f.id),
              subtype: "accident",
              priority: "urgent",
            },
      );
      await onDone(row);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  if (!car)
    return (
      <Empty
        title="Нет действующего автомобиля"
        text="Этот сценарий доступен после выдачи автомобиля."
      />
    );
  return (
    <>
      <div className="mini-title">
        <span className="mini-eyebrow">
          {inspection
            ? "ПЕРЕД ВЫЕЗДОМ"
            : `ПОМОЩЬ НА ДОРОГЕ · ШАГ ${step + 1} ИЗ 3`}
        </span>
        <h1>
          {inspection
            ? "Осмотр автомобиля"
            : ["Что произошло?", "Зафиксируем детали", "Проверьте обращение"][
                step
              ]}
        </h1>
        <p>
          {inspection
            ? "Четыре ракурса, пробег и топливо. Замечания передадим в сервис."
            : "Обращение поступит техническому отделу вместе с фотографиями."}
        </p>
      </div>
      <ErrorBox text={error} />
      {(inspection || step === 0) && (
        <section className="mini-surface">
          <label className="mini-field">
            Автомобиль
            <select
              value={vehicle}
              onChange={(e) => {
                setVehicle(e.target.value);
                const v = cars.find((x) => x.id === e.target.value);
                setMileage(String(v?.mileage || 0));
                setFuel(String(v?.fuel || 0));
                setShots({});
              }}
            >
              {cars.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.model} · {v.plate}
                </option>
              ))}
            </select>
          </label>
          {inspection ? (
            <div className="mini-numbers">
              <label className="mini-field">
                Пробег, км
                <input
                  type="number"
                  min={car.mileage}
                  value={mileage}
                  onChange={(e) => setMileage(e.target.value)}
                />
              </label>
              <label className="mini-field">
                Топливо, %
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={fuel}
                  onChange={(e) => setFuel(e.target.value)}
                />
              </label>
            </div>
          ) : (
            <>
              <label className="mini-field">
                Адрес или координаты
                <input
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="Улица, дом, ориентир"
                  maxLength={500}
                />
              </label>
              <button
                className="mini-link"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setError("");
                  try {
                    setLocation(await getLocation());
                  } catch (e: any) {
                    setError(e.message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <MapPin size={16} />
                Определить местоположение
              </button>
            </>
          )}
        </section>
      )}
      {(inspection || step === 1) && (
        <>
          <section className="mini-surface">
            <h3>
              {inspection
                ? "Четыре стороны автомобиля"
                : "Фотографии происшествия"}
            </h3>
            <div className="mini-photo-grid">
              {positions.map(([key, label]) => (
                <label
                  key={key}
                  className={"mini-photo " + (shots[key] ? "uploaded" : "")}
                >
                  <input
                    aria-label={`Фото: ${label}`}
                    type="file"
                    accept="image/jpeg,image/png"
                    capture="environment"
                    disabled={busy || !online}
                    onChange={(e) => photo(key, e.target.files?.[0])}
                  />
                  {shots[key] ? (
                    <CheckCircle2 size={24} />
                  ) : (
                    <Upload size={24} />
                  )}
                  <strong>{label}</strong>
                  <small>
                    {shots[key] ? "Фото загружено" : "Камера или файл"}
                  </small>
                </label>
              ))}
            </div>
          </section>
          <label className="mini-field mini-surface">
            {inspection
              ? "Замечания, если есть"
              : "Обстоятельства происшествия"}
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder={
                inspection
                  ? "Например: повреждение на правой двери"
                  : "Что произошло, есть ли повреждения"
              }
              maxLength={2000}
              rows={4}
            />
          </label>
        </>
      )}
      {!inspection && step === 2 && (
        <section className="mini-surface">
          <h3>{car.model}</h3>
          <p>
            <MapPin size={15} />
            {location}
          </p>
          <p>{notes}</p>
          <div className="mini-row">
            <span>Приложено фотографий</span>
            <b>{Object.keys(shots).length}</b>
          </div>
          <p className="mini-hint">
            Срочное обращение. Учебный срок реакции отдела — 15 минут.
          </p>
          <button className="mini-link" onClick={() => setStep(1)}>
            Изменить детали
          </button>
        </section>
      )}
      <Primary
        button={{
          text: inspection
            ? "Сохранить предсменный осмотр"
            : step < 2
              ? "Продолжить"
              : "Отправить обращение в сервис",
          busy,
          disabled:
            !online ||
            (inspection || step === 2
              ? !valid
              : step === 0
                ? !location.trim()
                : !notes.trim() || !Object.keys(shots).length),
        }}
        onClick={
          inspection || step === 2 ? submit : () => setStep((s) => s + 1)
        }
      />
    </>
  );
}
