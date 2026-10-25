import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeftRight, CircleCheck, LoaderCircle } from "lucide-react";
import { api, Data, Row, rub } from "./lib";
import "./crm.css";

type Report = {
  summary: {
    mode: "emulator" | "live";
    month: string;
    exported: number;
    skipped: number;
    documents: number;
    mismatches: number;
    calls: number;
    ms: number;
    at: string;
  };
  rows: {
    doc: string | null;
    kind: "sale" | "payment";
    contract: string | null;
    contract_id?: string | null;
    onec: number | null;
    ledger: number | null;
    ok: boolean;
    note: string;
  }[];
  trace: { call: string; ms: number }[];
};
type View = { report: Report | null; odata: string; sets: string[] };
const KIND = { sale: "Реализация", payment: "Поступление" };
const MONTHS = [
  "январь",
  "февраль",
  "март",
  "апрель",
  "май",
  "июнь",
  "июль",
  "август",
  "сентябрь",
  "октябрь",
  "ноябрь",
  "декабрь",
];
const month = (m: string) => MONTHS[Number(m.slice(5, 7)) - 1] + " " + m.slice(0, 4);

export function OnecPage({ data, open, toast }: { data: Data; open: (row: Row) => void; toast: (m: string) => void }) {
  const q = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("diff");
  const view = useQuery({ queryKey: ["onec"], queryFn: () => api<View>("/onec") });
  const run = async () => {
    setBusy(true);
    try {
      const report = await api<Report>("/onec/exchange", { method: "POST", body: "{}" });
      q.setQueryData(["onec"], (old: View | undefined) => (old ? { ...old, report } : old));
      toast(
        report.summary.exported
          ? `Выгружено документов: ${report.summary.exported}`
          : "Новых документов нет — всё уже в 1С",
      );
    } catch (e: any) {
      toast(e.message);
    } finally {
      setBusy(false);
    }
  };
  if (view.error) return <div className="error">{(view.error as Error).message}</div>;
  if (!view.data)
    return (
      <div className="cr-loading">
        <LoaderCircle className="spin" /> Подключаемся к 1С…
      </div>
    );
  const { report, odata, sets } = view.data;
  const s = report?.summary;
  const rows = report?.rows || [];
  const url = location.origin + odata;

  return (
    <div className="cr">
      <div className="cr-head">
        <div className="cr-source">
          <span className={"cr-dot " + (s?.mode || "emulator")} />
          <div>
            <b>{s?.mode === "live" ? "1С · живая база по OData" : "1С · эмулятор базы по стандартному OData"}</b>
            <small>
              Тот же протокол, что у 1С: <code>/odata/standard.odata/…</code>, <code>$filter</code>, <code>$top</code>/
              <code>$skip</code>, POST документа и <code>Post()</code>. Для живой базы достаточно адреса публикации и
              пользователя.
            </small>
          </div>
        </div>
        <div className="cr-sync">
          <small>
            {s ? `Обмен за ${month(s.month)} · ${s.calls} вызовов OData · ${s.ms} мс` : "Обмен ещё не запускался"}
          </small>
          <button className="button primary" disabled={busy} onClick={run}>
            {busy ? <LoaderCircle size={16} className="spin" /> : <ArrowLeftRight size={16} />} Выгрузить и сверить
          </button>
        </div>
      </div>

      {s && (
        <div className="cr-kpis">
          <div>
            <b>{s.exported}</b>
            <span>документов выгружено сейчас</span>
          </div>
          <div>
            <b>{s.skipped}</b>
            <span>уже были в 1С — повтор не создаёт дублей</span>
          </div>
          <div>
            <b>{s.documents}</b>
            <span>проведённых документов за месяц в 1С</span>
          </div>
          <div className={s.mismatches ? "bad" : ""}>
            <b>{s.mismatches}</b>
            <span>расхождений «учёт ↔ 1С»</span>
          </div>
        </div>
      )}

      {!report && (
        <div className="cr-table">
          <p className="cr-lead">
            Начисления аренды за прошлый месяц уйдут в 1С документами «Реализация товаров и услуг», оплаты —
            «Поступлением безналичных». В комментарии документа — договор и месяц, поэтому повторный обмен ничего не
            задвоит. После выгрузки стенд прочитает 1С обратно и сверит суммы в обе стороны. В базе 1С уже есть то, что
            бухгалтер внёс сам, — сверка это найдёт.
          </p>
        </div>
      )}

      {report && (
        <>
          <div className="list-toolbar">
            <div className="tabs">
              {[
                ["diff", `Сверка${s?.mismatches ? " · " + s.mismatches : ""}`],
                ["log", "Журнал OData"],
                ["http", "Доступ по HTTP"],
              ].map(([id, label]) => (
                <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
                  {label}
                </button>
              ))}
            </div>
          </div>

          {tab === "diff" && (
            <div className="cr-table">
              <table>
                <thead>
                  <tr>
                    <th>Документ 1С</th>
                    <th>Вид</th>
                    <th>Договор</th>
                    <th className="num">В 1С</th>
                    <th className="num">В учёте</th>
                    <th>Итог</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 80).map((r, i) => {
                    const row = data.contract.find((x) => x.id === r.contract_id);
                    return (
                      <tr key={(r.doc || "") + r.kind + (r.contract || "") + i} className={r.ok ? "" : "bad"}>
                        <td>
                          <b>{r.doc || "—"}</b>
                        </td>
                        <td>{KIND[r.kind]}</td>
                        <td>
                          {row ? (
                            <button className="link" onClick={() => open(row)}>
                              {r.contract}
                            </button>
                          ) : (
                            r.contract || "—"
                          )}
                        </td>
                        <td className="num">{r.onec != null ? rub(r.onec) : "—"}</td>
                        <td className="num">{r.ledger != null ? rub(r.ledger) : "—"}</td>
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
              {rows.length > 80 && (
                <p className="muted cr-note">Показаны первые 80 из {rows.length}: сначала расхождения.</p>
              )}
            </div>
          )}

          {tab === "log" && (
            <div className="cr-table">
              <table>
                <thead>
                  <tr>
                    <th>Вызов</th>
                    <th className="num">мс</th>
                  </tr>
                </thead>
                <tbody>
                  {report.trace.map((t, i) => (
                    <tr key={i}>
                      <td>
                        <code>{t.call}</code>
                      </td>
                      <td className="num">{t.ms}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted cr-note">
                Первые 40 вызовов обмена. Запись в живую 1С включается только отдельным флагом.
              </p>
            </div>
          )}

          {tab === "http" && (
            <div className="cr-table">
              <p className="cr-lead">
                Эмулятор вашей базы доступен по HTTP — его можно подключить к n8n или проверить curl. Ключ действует
                сутки.
              </p>
              <pre className="cr-code">{`curl '${url}${sets[2]}?$format=json&$top=3&$filter=Posted%20eq%20true'`}</pre>
              <p className="muted cr-note">Опубликованные наборы: {sets.join(", ")}.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
