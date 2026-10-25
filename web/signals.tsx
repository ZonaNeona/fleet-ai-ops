import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, FileSpreadsheet, Sheet, Zap } from "lucide-react";
import { api, Data, Row } from "./lib";
import "./signals.css";

type Signal = {
  rule: string;
  label: string;
  title: string;
  reason: string;
  action: string;
  target: string | null;
  code: string;
};
type Signals = { summary: { rule: string; label: string; count: number }[]; rows: Signal[] };
// Where a signal without a ledger object leads: the screen that owns it.
const PAGE: Record<string, string> = { "hiring-stuck": "crm", "crm-paid-gap": "crm", "call-low": "calls" };

/* «Сделать сейчас»: rules over the ledger, service, Bitrix24 and calls, no model; a signal goes away once its cause is fixed. */
export function SignalsWidget({
  data,
  open,
  go,
}: {
  data: Data;
  open: (row: Row) => void;
  go: (page: string) => void;
}) {
  const q = useQuery({ queryKey: ["signals"], queryFn: () => api<Signals>("/signals"), refetchInterval: 60000 });
  const [rule, setRule] = useState("");
  const owner = ["owner", "admin", "finance"].includes(data.session.role);
  const exp = useQuery({
    queryKey: ["export"],
    queryFn: () => api<{ sheets: boolean; url: string | null }>("/export"),
    enabled: owner,
  });
  const [sent, setSent] = useState("");
  const mirror = async () => {
    setSent("…");
    try {
      const r = await api<{ url: string }>("/export/sheets", { method: "POST", body: "{}" });
      setSent(r.url);
    } catch (e: any) {
      setSent("");
      alert(e.message);
    }
  };
  if (!q.data) return null;
  const rows = q.data.rows.filter((r) => !rule || r.rule === rule);
  const target = (s: Signal) =>
    s.target ? [...data.contract, ...data.ticket].find((x) => x.id === s.target) : undefined;

  return (
    <section className="sg">
      <div className="sg-head">
        <h2>
          <Zap size={18} /> Сделать сейчас {q.data.rows.length ? <b>{q.data.rows.length}</b> : null}
        </h2>
        {owner && (
          <div className="sg-export">
            <a className="button ghost" href="/api/v1/export.xlsx">
              <FileSpreadsheet size={15} /> XLSX: сводка, сигналы, документы
            </a>
            {exp.data?.sheets && (
              <button className="button ghost" onClick={mirror} disabled={sent === "…"}>
                <Sheet size={15} /> {sent && sent !== "…" ? "Обновлено" : "В Google Таблицу"}
              </button>
            )}
            {sent && sent !== "…" && (
              <a href={sent} target="_blank" rel="noreferrer">
                открыть
              </a>
            )}
          </div>
        )}
        <div className="sg-chips">
          <button className={!rule ? "on" : ""} onClick={() => setRule("")}>
            Все
          </button>
          {q.data.summary.map((x) => (
            <button key={x.rule} className={rule === x.rule ? "on" : ""} onClick={() => setRule(x.rule)}>
              {x.label} · {x.count}
            </button>
          ))}
        </div>
      </div>
      {!q.data.rows.length && <p className="muted">Срочного нет: долги, аренды, сервис, найм и звонки в норме.</p>}
      <div className="sg-list">
        {rows.slice(0, 8).map((s, i) => {
          const row = target(s);
          const go_ = () => (row ? open(row) : PAGE[s.rule] ? go(PAGE[s.rule]) : undefined);
          return (
            <button className={"sg-item " + s.rule} key={s.rule + s.code + i} onClick={go_}>
              <AlertTriangle size={16} />
              <span>
                <small>{s.label}</small>
                <b>{s.title}</b>
                <em>{s.reason}</em>
                <i>{s.action}</i>
              </span>
              <ChevronRight size={16} />
            </button>
          );
        })}
      </div>
      {rows.length > 8 && (
        <p className="muted sg-more">Ещё {rows.length - 8} — спросите помощника «что сделать сейчас».</p>
      )}
    </section>
  );
}
