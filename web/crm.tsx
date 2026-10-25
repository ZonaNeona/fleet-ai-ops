import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CircleCheck, Clock3, LoaderCircle, RefreshCw, Server, UserRound } from "lucide-react";
import { api, Data, Row, rub } from "./lib";
import { B24AppTab } from "./b24app";
import "./crm.css";

type Deal = {
  id: string;
  title: string;
  funnel: number;
  stage: string;
  open: boolean;
  amount: string;
  manager: string;
  source: string;
  created: string;
  days_in_stage: number;
  stuck: boolean;
  contract: string | null;
  plate: string | null;
  experience?: string | null;
};
type Crm = {
  mode: "emulator" | "live";
  synced_at: string;
  funnels: { id: number; name: string; key: string; stages: { id: string; name: string; semantics: string }[] }[];
  deals: Deal[];
  leads: {
    id: string;
    title: string;
    name: string;
    status: string;
    source: string;
    manager: string;
    created: string;
  }[];
  reconciliation: {
    deal: string;
    title: string;
    contract: string;
    contract_id: string | null;
    crm_paid: string;
    ledger_paid: string | null;
    diff: string | null;
    ok: boolean;
    note: string;
  }[];
  trace: { method: string; params: any; ms: number; rows: number; total?: number; next?: number }[];
  summary: {
    hiring_total: number;
    hiring_won: number;
    hiring_conversion: number;
    stuck: number;
    leads_new: number;
    mismatches: number;
    calls: number;
    ms: number;
  };
  tasks: { id: string; TITLE: string; DEADLINE: string; createdDate: string }[];
};
const LEAD: Record<string, string> = {
  NEW: "новый",
  IN_PROCESS: "в работе",
  JUNK: "некачественный",
  CONVERTED: "сконвертирован",
};
const when = (v: string) =>
  new Date(v).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export function CrmPage({ data, open, toast }: { data: Data; open: (row: Row) => void; toast: (m: string) => void }) {
  const q = useQueryClient();
  const [tab, setTab] = useState("hiring");
  const [busy, setBusy] = useState(false);
  const crm = useQuery({ queryKey: ["crm"], queryFn: () => api<Crm>("/crm") });
  const sync = async () => {
    setBusy(true);
    try {
      const snap = await api<Crm>("/crm/sync", { method: "POST", body: "{}" });
      q.setQueryData(["crm"], (old: Crm | undefined) => ({ ...snap, tasks: old?.tasks || [] }));
    } catch (e: any) {
      toast(e.message);
    } finally {
      setBusy(false);
    }
  };
  if (crm.error) return <div className="error">{(crm.error as Error).message}</div>;
  if (!crm.data)
    return (
      <div className="cr-loading">
        <LoaderCircle className="spin" /> Читаем Битрикс24…
      </div>
    );
  const c = crm.data;
  const funnel = c.funnels.find((f) => f.key === tab);

  return (
    <div className="cr">
      <div className="cr-head">
        <div className="cr-source">
          <span className={"cr-dot " + c.mode} />
          <div>
            <b>{c.mode === "live" ? "Битрикс24 · живой портал, только чтение" : "Битрикс24 · эмулятор портала"}</b>
            <small>
              {c.mode === "live"
                ? "Входящий вебхук; методы из закрытого списка, без записи."
                : "Отвечает в формате REST портала: строки-числа, постраничность по 50, блок time. Для живого портала достаточно вебхука."}
            </small>
          </div>
        </div>
        <div className="cr-sync">
          <small>
            Синхронизация {when(c.synced_at)} · {c.summary.calls} вызовов REST · {c.summary.ms} мс
          </small>
          <button className="button secondary" disabled={busy} onClick={sync}>
            {busy ? <LoaderCircle size={16} className="spin" /> : <RefreshCw size={16} />} Синхронизировать
          </button>
        </div>
      </div>

      <div className="cr-kpis">
        <div>
          <b>{c.summary.hiring_conversion}%</b>
          <span>
            отклик → на линии ({c.summary.hiring_won} из {c.summary.hiring_total})
          </span>
        </div>
        <div className={c.summary.stuck ? "warn" : ""}>
          <b>{c.summary.stuck}</b>
          <span>сделок зависли дольше 3 дней</span>
        </div>
        <div>
          <b>{c.summary.leads_new}</b>
          <span>новых лидов за неделю</span>
        </div>
        <div className={c.summary.mismatches ? "bad" : ""}>
          <b>{c.summary.mismatches}</b>
          <span>расхождений «оплачено в CRM ↔ учёт»</span>
        </div>
      </div>

      <div className="list-toolbar">
        <div className="tabs">
          {[
            ["hiring", "Найм водителей"],
            ["rental", "Прокат"],
            ["leads", `Лиды · ${c.leads.length}`],
            ["money", `Сверка оплат${c.summary.mismatches ? " · " + c.summary.mismatches : ""}`],
            ["app", "Приложение Б24 · PHP + Vue"],
            ["log", "Журнал REST"],
          ].map(([id, label]) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {funnel && (
        <div className="kanban cr-kanban">
          {funnel.stages.map((st) => {
            const deals = c.deals.filter((d) => d.funnel === funnel.id && d.stage === st.id);
            return (
              <div className={"kanban-column " + st.semantics} key={st.id}>
                <div className="kanban-heading">
                  <span>{st.name}</span>
                  <b>{deals.length}</b>
                </div>
                {deals.map((d) => (
                  <div className={"kanban-card cr-card" + (d.stuck ? " stuck" : "")} key={d.id}>
                    <div className="kanban-card-top">
                      <small>B24 #{d.id}</small>
                      {d.stuck && (
                        <span className="cr-stuck">
                          <AlertTriangle size={11} /> {d.days_in_stage} дн. на стадии
                        </span>
                      )}
                    </div>
                    <h3>{d.title}</h3>
                    <p>
                      {d.source}
                      {d.experience ? ` · стаж ${d.experience} лет` : ""}
                      {d.contract ? ` · договор ${d.contract}` : ""}
                    </p>
                    <div className="kanban-meta">
                      <span>
                        <UserRound size={12} /> {d.manager}
                      </span>
                      {Number(d.amount) > 0 && <strong>{rub(d.amount)}</strong>}
                    </div>
                  </div>
                ))}
                {!deals.length && <div className="kanban-empty">Пусто</div>}
              </div>
            );
          })}
        </div>
      )}

      {tab === "leads" && (
        <div className="cr-table">
          <table>
            <thead>
              <tr>
                <th>Лид</th>
                <th>Контакт</th>
                <th>Источник</th>
                <th>Статус</th>
                <th>Ответственный</th>
                <th>Создан</th>
              </tr>
            </thead>
            <tbody>
              {c.leads.map((l) => (
                <tr key={l.id}>
                  <td>
                    <b>{l.title}</b>
                    <small>B24 #{l.id}</small>
                  </td>
                  <td>{l.name}</td>
                  <td>{l.source}</td>
                  <td>
                    <span className={"cr-pill " + l.status}>{LEAD[l.status] || l.status}</span>
                  </td>
                  <td>{l.manager}</td>
                  <td>{when(l.created)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted cr-note">
            <Clock3 size={13} /> Часть лидов датирована позже сегодня — они появятся при следующей синхронизации, как в
            живом портале.
          </p>
          <p className="muted cr-note">
            Заявки с клиентского сайта приходят сюда лидом и сделкой в воронке «Прокат»:{" "}
            <a href="/auto" target="_blank" rel="noreferrer">
              открыть сайт таксопарка
            </a>
          </p>
        </div>
      )}

      {tab === "money" && (
        <div className="cr-table">
          <p className="cr-lead">
            Сделки проката в Битрикс24 хранят поле «Оплачено» — его ставит менеджер. Учёт видит только деньги, которые
            реально пришли. Здесь видно, где они разошлись.
          </p>
          <table>
            <thead>
              <tr>
                <th>Сделка</th>
                <th>Договор</th>
                <th className="num">Оплачено в CRM</th>
                <th className="num">Пришло в учёт</th>
                <th className="num">Разница</th>
                <th>Итог</th>
              </tr>
            </thead>
            <tbody>
              {c.reconciliation.map((r) => {
                const row = data.contract.find((x) => x.id === r.contract_id);
                return (
                  <tr key={r.deal} className={r.ok ? "" : "bad"}>
                    <td>
                      <b>{r.title}</b>
                      <small>B24 #{r.deal}</small>
                    </td>
                    <td>
                      {row ? (
                        <button className="link" onClick={() => open(row)}>
                          {r.contract}
                        </button>
                      ) : (
                        r.contract
                      )}
                    </td>
                    <td className="num">{rub(r.crm_paid)}</td>
                    <td className="num">{r.ledger_paid != null ? rub(r.ledger_paid) : "—"}</td>
                    <td className="num">{r.diff && Number(r.diff) !== 0 ? rub(r.diff) : "—"}</td>
                    <td>
                      {r.ok ? (
                        <span className="cr-ok">
                          <CircleCheck size={14} /> сходится
                        </span>
                      ) : (
                        <span className="cr-bad">
                          <AlertTriangle size={14} /> {r.note}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {tab === "app" && (
        <B24AppTab
          deals={c.deals}
          stages={Object.fromEntries(c.funnels.flatMap((f) => f.stages.map((st) => [st.id, st.name])))}
          toast={toast}
        />
      )}

      {tab === "log" && (
        <div className="cr-table">
          <p className="cr-lead">
            Последняя синхронизация — это настоящие вызовы REST в порядке выполнения. Списки читаются постранично (по
            50), пока портал отдаёт <code>next</code>. Код одинаковый для эмулятора и живого портала.
          </p>
          <table>
            <thead>
              <tr>
                <th>Метод</th>
                <th>Параметры</th>
                <th className="num">Строк</th>
                <th className="num">Всего</th>
                <th className="num">next</th>
                <th className="num">мс</th>
              </tr>
            </thead>
            <tbody>
              {c.trace.map((t, i) => (
                <tr key={i}>
                  <td>
                    <code>{t.method}</code>
                  </td>
                  <td>
                    <code className="cr-params">{JSON.stringify(t.params)}</code>
                  </td>
                  <td className="num">{t.rows}</td>
                  <td className="num">{t.total ?? "—"}</td>
                  <td className="num">{t.next ?? "—"}</td>
                  <td className="num">{t.ms}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!!c.tasks.length && (
            <>
              <h3 className="cr-h">
                <Server size={15} /> Задачи, созданные агентом после подтверждения
              </h3>
              <ul className="cr-tasks">
                {c.tasks.map((t) => (
                  <li key={t.id}>
                    <b>{t.TITLE}</b>
                    <small>
                      #{t.id} · срок {when(t.DEADLINE)}
                    </small>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
