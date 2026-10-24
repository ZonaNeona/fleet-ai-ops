import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, Zap } from "lucide-react";
import { api, Data, Row } from "./lib";
import "./signals.css";

type Signal = { rule: string; label: string; title: string; reason: string; action: string; target: string | null; code: string };
type Signals = { summary: { rule: string; label: string; count: number }[]; rows: Signal[] };
// Where a signal without a ledger object leads: the screen that owns it.
const PAGE: Record<string, string> = { "hiring-stuck": "crm", "crm-paid-gap": "crm", "call-low": "calls" };

/* «Сделать сейчас»: правила над учётом, сервисом, Битрикс24 и звонками — без модели; сигнал исчезает, когда причина устранена. */
export function SignalsWidget({ data, open, go }: { data: Data; open: (row: Row) => void; go: (page: string) => void }) {
  const q = useQuery({ queryKey: ["signals"], queryFn: () => api<Signals>("/signals"), refetchInterval: 60000 });
  const [rule, setRule] = useState("");
  if (!q.data) return null;
  const rows = q.data.rows.filter((r) => !rule || r.rule === rule);
  const target = (s: Signal) =>
    s.target ? [...data.contract, ...data.ticket].find((x) => x.id === s.target) : undefined;

  return (
    <section className="sg">
      <div className="sg-head">
        <h2><Zap size={18} /> Сделать сейчас {q.data.rows.length ? <b>{q.data.rows.length}</b> : null}</h2>
        <div className="sg-chips">
          <button className={!rule ? "on" : ""} onClick={() => setRule("")}>Все</button>
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
      {rows.length > 8 && <p className="muted sg-more">Ещё {rows.length - 8} — спросите помощника «что сделать сейчас».</p>}
    </section>
  );
}
