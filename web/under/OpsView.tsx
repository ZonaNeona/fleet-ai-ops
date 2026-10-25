import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, CreditCard, Database, Gauge, RotateCcw } from "lucide-react";
import { api, rub } from "../lib";
import { Say, Section, useEngineer } from "./kit";

type Obs = {
  routes: { route: string; count: number; p50: number; p95: number; errors: number }[];
  requests: number;
  errors: { route: string; status: number; at: string }[];
  redis: { enabled: boolean; ok: boolean; ping_ms?: number; used_mb?: number; keys?: number };
  stats: Record<string, number>;
  sentry: boolean;
  hermes: { configured: boolean; ok?: boolean; ms?: number };
  documents_llm: "local" | "cloud";
  ollama: boolean;
  queue: {
    worker_heartbeat_age_seconds: number;
    jobs: Record<string, number>;
    jobs_failed_today: number;
    queue_wait_seconds: number;
    ai_spend_usd_today: number;
    ai_calls_today: number;
  };
};
type Pay = {
  mode: "emulator" | "live";
  telegram: boolean;
  webhook: string;
  payments: {
    id: string;
    code: string;
    label: string;
    amount: string;
    status: string;
    provider: { name: string; mode: string; id?: string };
    log: { at: string; step: string; result?: string; request?: string }[];
  }[];
};
const STATUS: Record<string, string> = {
  pending: "ждёт оплаты",
  paid: "проведён",
  refunded: "возвращён",
  canceled: "отменён",
};

/* Эксплуатация: метрики, очередь, Redis, лимиты и платежи — те же цифры, что /api/metrics отдаёт Prometheus. */
export function OpsView() {
  const eng = useEngineer();
  const q = useQueryClient();
  const obs = useQuery({
    queryKey: ["observability"],
    queryFn: () => api<Obs>("/observability"),
    refetchInterval: 10000,
  });
  const pay = useQuery({ queryKey: ["payments-journal"], queryFn: () => api<Pay>("/payments") });
  const [busy, setBusy] = useState("");
  const refund = async (id: string) => {
    setBusy(id);
    try {
      await api(`/payments/${id}/refund`, { method: "POST", body: "{}" });
      await q.invalidateQueries({ queryKey: ["payments-journal"] });
    } finally {
      setBusy("");
    }
  };
  const o = obs.data;
  const p = pay.data;

  return (
    <div className="k-stage k-mcp">
      <div className="k-mcp-main">
        <span className="k-eyebrow">Эксплуатация · метрики, очередь, Redis</span>
        <h3 className="k-h">Как стенд себя чувствует прямо сейчас</h3>
        <p className="k-lead">
          <Say
            simple="Сколько длятся запросы, не копится ли очередь, жив ли воркер и сколько сегодня ушло на модели. Эти же цифры забирает Prometheus, а в репозитории лежит готовый дашборд Grafana."
            eng="/api/metrics — prometheus_client: гистограмма задержек по шаблону маршрута, счётчики ответов и отказов по лимитам; очередь, пульс воркера и расход на модели читаются из PostgreSQL при каждом сборе, поэтому API и воркер не расходятся. Redis — только ускоритель: лимиты INCR+EXPIRE по солёному хешу IP, кэш отчёта с поколением на пространство, pub/sub для живой ленты. Очередь заданий осталась в PostgreSQL: задание и проводки фиксируются одной транзакцией (ADR 0002). Sentry включается переменной SENTRY_DSN."
          />
        </p>
        {o && (
          <div className="k-ops-kpis">
            <div>
              <Gauge size={15} />
              <b>{o.queue.worker_heartbeat_age_seconds} с</b>
              <span>пульс воркера</span>
            </div>
            <div>
              <Activity size={15} />
              <b>{o.queue.jobs.pending || 0}</b>
              <span>заданий ждут · ожидание {o.queue.queue_wait_seconds} с</span>
            </div>
            <div className={o.queue.jobs_failed_today ? "bad" : ""}>
              <b>{o.queue.jobs_failed_today}</b>
              <span>заданий упало сегодня</span>
            </div>
            <div>
              <b>${o.queue.ai_spend_usd_today.toFixed(4)}</b>
              <span>на модели сегодня · {o.queue.ai_calls_today} вызовов</span>
            </div>
          </div>
        )}
        <Section title={`Задержки по маршрутам · последние ${o?.requests ?? "…"} запросов этого процесса`}>
          <div className="k-ops-table">
            <table>
              <thead>
                <tr>
                  <th>Маршрут</th>
                  <th className="num">Запросов</th>
                  <th className="num">p50, мс</th>
                  <th className="num">p95, мс</th>
                  <th className="num">5xx</th>
                </tr>
              </thead>
              <tbody>
                {(o?.routes || []).map((r) => (
                  <tr key={r.route}>
                    <td>
                      <code>{r.route}</code>
                    </td>
                    <td className="num">{r.count}</td>
                    <td className="num">{r.p50}</td>
                    <td className="num">{r.p95}</td>
                    <td className="num">{r.errors || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        <Section title="Онлайн-оплаты · ЮKassa и Telegram">
          <p className="k-hint">
            {p?.mode === "live"
              ? "Тестовый магазин ЮKassa по ключам."
              : "Эмулятор ЮKassa: тот же API v3, страница оплаты и уведомление."}{" "}
            Оплатите долг водителя в Mini App (роль «Водитель» → «Оплатить») — платёж появится здесь. Уведомлению не
            верим на слово: перечитываем платёж у провайдера и проводим один раз по его id.
          </p>
          <p className="k-hint k-demo-note">
            Демо: магазин — эмулятор, оплата внутри Telegram на стенде не подключена. В рабочей версии подключается
            магазин ЮKassa / Т-Кассы / CloudPayments ключами и токен провайдера в BotFather; чеки 54-ФЗ — онлайн-касса
            провайдера; карта и СБП. Перечитывание платежа, идемпотентность и возврат сторно — тот же код, что здесь.
          </p>
          {!p?.payments.length && <p className="k-hint">Онлайн-оплат пока не было.</p>}
          {(p?.payments || []).map((x) => (
            <div className="k-pay" key={x.id}>
              <div className="k-pay-head">
                <CreditCard size={15} />
                <b>{x.code}</b>
                <span>{x.label}</span>
                <strong>{rub(x.amount)}</strong>
                <span className={"k-pay-status " + x.status}>{STATUS[x.status] || x.status}</span>
                {x.status === "paid" && x.provider?.name === "yookassa" && (
                  <button className="k-btn" disabled={busy === x.id} onClick={() => refund(x.id)}>
                    <RotateCcw size={13} /> Вернуть
                  </button>
                )}
              </div>
              <ol>
                {x.log.map((l, i) => (
                  <li key={i}>
                    <small>{l.at.slice(11, 19)}</small> {l.step}
                    {l.result ? " — " + l.result : ""}
                    {eng && l.request ? ` · ${l.request}` : ""}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </Section>
      </div>

      <aside className="k-inspector">
        <span className="k-eyebrow">Redis</span>
        <div className="k-checks">
          <div className={o?.redis.ok ? "ok" : "bad"}>
            <b>
              <Database size={12} />{" "}
              {o?.redis.ok
                ? `на связи · ${o.redis.ping_ms} мс`
                : o?.redis.enabled
                  ? "недоступен — работаем без него"
                  : "не настроен"}
            </b>
            {o?.redis.ok && (
              <small>
                {o.redis.used_mb} МБ · ключей {o.redis.keys}
              </small>
            )}
          </div>
          <div className="ok">
            <b>Лимиты</b>
            <small>
              пропущено {o?.stats.allowed ?? 0} · отказано {o?.stats.limited ?? 0}
            </small>
          </div>
          <div className="ok">
            <b>Кэш отчёта</b>
            <small>
              попаданий {o?.stats.cache_hit ?? 0} · промахов {o?.stats.cache_miss ?? 0}
            </small>
          </div>
          <div className="ok">
            <b>Живая лента</b>
            <small>событий разослано {o?.stats.published ?? 0}</small>
          </div>
          <div className={o?.hermes.ok ? "ok" : "bad"}>
            <b>Hermes Agent</b>
            <small>
              {!o?.hermes.configured
                ? "не подключён: агент отвечает встроенным циклом"
                : o.hermes.ok
                  ? `на связи · ${o.hermes.ms} мс · профиль fleet`
                  : "недоступен — отвечает встроенный цикл"}
            </small>
          </div>
          <div className="ok">
            <b>Документы с ПДн</b>
            <small>
              {o?.documents_llm === "local"
                ? "читает только локальная модель (Ollama) — в облако не уходят"
                : `облачная vision-модель; локальная — переменной PII_LOCAL=1${o?.ollama ? "" : " и OLLAMA_URL"}`}
            </small>
          </div>
          <div className={o?.sentry ? "ok" : "bad"}>
            <b>Sentry</b>
            <small>{o?.sentry ? "ошибки уходят в Sentry" : "выключен: SENTRY_DSN не задан"}</small>
          </div>
        </div>
        <Section title="Последние ошибки 5xx">
          {o?.errors.length ? (
            <div className="k-checks">
              {o.errors.map((e, i) => (
                <div key={i} className="bad">
                  <b>
                    {e.status} · {e.route}
                  </b>
                  <small>{e.at}</small>
                </div>
              ))}
            </div>
          ) : (
            <p className="k-hint">Ошибок нет.</p>
          )}
        </Section>
        <Section title="Prometheus и Grafana локально">
          <pre className="k-pre">
            docker compose --profile observability up{"\n"}# Grafana → http://localhost:3000, дашборд «Fleet»
          </pre>
          <p className="k-hint">
            <a href="/api/metrics" target="_blank" rel="noreferrer">
              /api/metrics
            </a>{" "}
            — то, что собирает Prometheus.
          </p>
        </Section>
      </aside>
    </div>
  );
}
