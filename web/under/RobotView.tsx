import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Download, ExternalLink, LoaderCircle, Play, RotateCw } from "lucide-react";
import { api } from "../lib";
import { Say, Section } from "./kit";

type Step = { title: string; status: string; ms: number; shot?: string; url?: string };
type Rec = { resolution: string; plate: string; amount: number; date?: string; state: string; note: string };
type Run = {
  id: string;
  status: string;
  created: string;
  steps: Step[];
  reconciliation?: Rec[];
  plates?: number;
  seconds?: number;
  error?: string | null;
  loaded?: number;
};
const STATE: Record<string, [string, string]> = {
  ok: ["сходится", "ok"],
  amount: ["сумма отличается", "bad"],
  "portal-only": ["только на портале", "bad"],
  "ledger-only": ["только в учёте", "warn"],
  loaded: ["загружено роботом", "ok"],
};

/* Playwright robot: the training fines portal → reconcile with what n8n brought → load what is new into the ledger. */
export function RobotView() {
  const q = useQueryClient();
  const robot = useQuery({
    queryKey: ["robot"],
    queryFn: () => api<{ available: boolean; run: Run | null; ledger: number }>("/robot"),
    refetchInterval: (query) => (["queued", "running"].includes(query.state.data?.run?.status || "") ? 2000 : false),
  });
  const [shot, setShot] = useState("");
  const [busy, setBusy] = useState(false);
  const run = robot.data?.run;
  const start = async () => {
    setBusy(true);
    try {
      await api("/robot/run", { method: "POST", body: "{}" });
      await q.invalidateQueries({ queryKey: ["robot"] });
    } catch (e: any) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  };
  const load = async () => {
    if (!run) return;
    setBusy(true);
    try {
      await api(`/robot/${run.id}/load`, { method: "POST", body: "{}" });
      await q.invalidateQueries({ queryKey: ["robot"] });
    } finally {
      setBusy(false);
    }
  };
  const working = ["queued", "running"].includes(run?.status || "");
  const [syncing, setSyncing] = useState(false);
  const fetchFines = async () => {
    setSyncing(true);
    try {
      await api("/integrations/run", { method: "POST", body: JSON.stringify({ source: "fines" }) });
      for (let i = 0; i < 20; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const r = await api<{ ledger: number }>("/robot");
        if (r.ledger) break;
      }
      await q.invalidateQueries({ queryKey: ["robot"] });
    } catch (e: any) {
      alert(e.message);
    } finally {
      setSyncing(false);
    }
  };
  const rec = run?.reconciliation || [];
  const fresh = rec.filter((r) => r.state === "portal-only").length;
  const src = (name: string) => (run ? `/api/v1/robot/${run.id}/shot/${name}` : "");
  const current = shot || [...(run?.steps || [])].reverse().find((s) => s.shot)?.shot || "";

  return (
    <div className="k-stage k-mcp">
      <div className="k-mcp-main">
        <span className="k-eyebrow">Робот · Playwright · Chromium</span>
        <h3 className="k-h">Штрафы с портала — без ручного ввода</h3>
        <p className="k-lead">
          <Say
            simple="Робот открывает портал штрафов, вставляет госномера машин такси и выкупа, листает страницы, переживает сбои портала и сверяет найденное с тем, что пришло в учёт через n8n. Новые постановления можно одним нажатием загрузить в учёт — водитель увидит их в Mini App."
            eng="app/robot.py: Playwright sync API в отдельном процессе (браузер не остаётся в памяти воркера); троттлинг 0,4 с, 503/429 — повтор с нарастающей паузой, снимок каждого шага. Портал — учебный (app/gov.py): капча-заглушка отдаёт код автотестам через data-test-code — так делают на тестовых контурах; настоящую капчу робот не решает."
          />
        </p>
        <div className="k-mcp-key">
          <button className="k-btn primary" disabled={busy || working || !robot.data?.available} onClick={start}>
            {working ? <LoaderCircle size={14} className="spin" /> : <Play size={14} />}{" "}
            {working ? "Робот работает…" : "Запустить робота"}
          </button>
          <a className="k-btn" href="/gov" target="_blank" rel="noreferrer">
            <ExternalLink size={14} /> Учебный портал
          </a>
          {run?.status === "done" && fresh > 0 && (
            <button className="k-btn" disabled={busy} onClick={load}>
              <Download size={14} /> Загрузить в учёт новые · {fresh}
            </button>
          )}
        </div>
        {robot.data && !robot.data.available && <p className="k-hint">Playwright на этом сервере не установлен.</p>}
        {robot.data?.available && robot.data.ledger === 0 && (
          <p className="k-hint">
            В учёте пока нет штрафов из n8n — сверке не с чем сравнивать.{" "}
            <button className="k-btn" disabled={syncing} onClick={fetchFines}>
              {syncing ? <LoaderCircle size={13} className="spin" /> : <RotateCw size={13} />} Сначала забрать штрафы
              через n8n
            </button>
          </p>
        )}
        {run && (
          <Section
            title={`Запуск ${new Date(run.created).toLocaleTimeString("ru-RU")} · ${run.plates ?? "…"} ТС${run.seconds ? ` · ${run.seconds} с` : ""}`}
          >
            {run.error && (
              <p className="k-hint">
                <CircleAlert size={13} /> {run.error}
              </p>
            )}
            <div className="k-robot-shot">{current && <img src={src(current)} alt="Снимок шага робота" />}</div>
            <ol className="k-robot-steps">
              {run.steps.map((s, i) => (
                <li
                  key={i}
                  className={s.status + (s.shot === current ? " on" : "")}
                  onClick={() => s.shot && setShot(s.shot)}
                >
                  {s.status === "retry" ? (
                    <RotateCw size={13} />
                  ) : s.status === "error" ? (
                    <CircleAlert size={13} />
                  ) : (
                    <CircleCheck size={13} />
                  )}
                  <span>{s.title}</span>
                  <small>{(s.ms / 1000).toFixed(1)} с</small>
                </li>
              ))}
            </ol>
          </Section>
        )}
      </div>
      <aside className="k-inspector">
        <span className="k-eyebrow">Сверка: портал ↔ учёт (n8n)</span>
        {!rec.length && <p className="k-hint">Запустите робота — здесь появятся постановления и их сверка с учётом.</p>}
        <div className="k-checks">
          {rec.map((r, i) => {
            const [label, tone] = STATE[r.state] || [r.state, "warn"];
            return (
              <div key={i} className={tone === "ok" ? "ok" : "bad"}>
                <b>
                  {r.plate} · {Number(r.amount).toLocaleString("ru-RU")} ₽ · {label}
                </b>
                <small>
                  {r.resolution} — {r.note}
                </small>
              </div>
            );
          })}
        </div>
        {rec.some((r) => r.state === "ledger-only") && (
          <p className="k-hint">«Только в учёте»: n8n ещё не синхронизировал портал или постановление уже оплачено.</p>
        )}
      </aside>
    </div>
  );
}
