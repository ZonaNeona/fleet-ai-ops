import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CircleCheck,
  CircleDashed,
  CircleMinus,
  CircleX,
  LoaderCircle,
  Mic,
  PhoneIncoming,
  Sparkles,
} from "lucide-react";
import { api } from "./lib";
import "./calls.css";

type Item = { key: string; status: string; evidence: string; reason: string };
type Review = {
  transcript: string;
  seconds: number;
  stt: { model: string; cost: string; ms: number };
  review: { model: string; cost: string; ms: number; tokens: number };
  summary: string;
  topic: string;
  outcome: string;
  advice: string;
  items: Item[];
  score: number | null;
  at: string;
};
type Call = {
  id: string;
  title: string;
  caller: string;
  seconds: number;
  audio: string;
  review: Review | null;
  job: { state: string; error?: string } | null;
};
type Calls = { rows: Call[]; checklist: { key: string; label: string; weight: number }[]; average: number | null };

const ICON: Record<string, any> = {
  supported: CircleCheck,
  partial: CircleDashed,
  not_found: CircleX,
  not_applicable: CircleMinus,
};
const LABEL: Record<string, string> = {
  supported: "сделано",
  partial: "частично",
  not_found: "не сделано",
  not_applicable: "не нужно",
};
const tone = (s: number | null) => (s == null ? "" : s >= 80 ? "good" : s >= 50 ? "mid" : "bad");
const usd = (v: string | number) => "$" + Number(v || 0).toFixed(4);

export function CallsPage({ toast }: { toast: (m: string) => void }) {
  const q = useQueryClient();
  const [picked, setPicked] = useState<string | null>(null);
  const calls = useQuery({
    queryKey: ["calls"],
    queryFn: () => api<Calls>("/calls"),
    refetchInterval: (query) =>
      query.state.data?.rows.some((r) => !r.review && r.job && ["pending", "running"].includes(r.job.state))
        ? 2500
        : false,
  });
  if (calls.error) return <div className="error">{(calls.error as Error).message}</div>;
  if (!calls.data)
    return (
      <div className="cl-loading">
        <LoaderCircle className="spin" /> Загружаем звонки…
      </div>
    );
  const rows = calls.data.rows;
  const call = rows.find((r) => r.id === picked) || rows[0];
  const label = Object.fromEntries(calls.data.checklist.map((c) => [c.key, c]));
  const reviewIt = async (id: string) => {
    try {
      await api(`/calls/${id}/review`, { method: "POST", body: "{}" });
      q.invalidateQueries({ queryKey: ["calls"] });
    } catch (e: any) {
      toast(e.message);
    }
  };
  const busy = (c: Call) => !c.review && c.job && ["pending", "running"].includes(c.job.state);
  const ring = async () => {
    try {
      const r = await api<{ activity: number; call: string; title: string }>("/telephony/simulate", {
        method: "POST",
        body: "{}",
      });
      toast(`АТС прислала звонок «${r.title}»: дело №${r.activity} в Битрикс24, разбор запущен`);
      setPicked(r.call);
      q.invalidateQueries({ queryKey: ["calls"] });
    } catch (e: any) {
      toast(e.message);
    }
  };

  return (
    <div className="cl">
      <div className="cl-intro">
        <Mic size={18} />
        <div>
          <b>Звонки диспетчерской.</b> Запись → распознавание речи моделью с аудио-входом → разбор по чек-листу
          диспетчера моделью → балл считает код. Записи учебные, синтезированы голосами; стенд не знает их сценарий и
          слышит их как обычные звонки. Разбор — настоящий вызов моделей, поэтому каждая запись разбирается один раз и
          результат виден всем.
        </div>
        <button
          className="button secondary"
          onClick={ring}
          title="Подписанный вебхук виртуальной АТС (формат Mango Office) → дело-звонок в Битрикс24 → разбор записи"
        >
          <PhoneIncoming size={16} /> Позвонить в диспетчерскую · АТС
        </button>
        <div className="cl-avg">
          <b className={tone(calls.data.average)}>{calls.data.average ?? "—"}</b>
          <span>средний балл</span>
        </div>
      </div>

      <div className="cl-grid">
        <div className="cl-list">
          {rows.map((r) => (
            <button
              key={r.id}
              className={"cl-row" + (call?.id === r.id ? " active" : "")}
              onClick={() => setPicked(r.id)}
            >
              <span className={"cl-score " + tone(r.review?.score ?? null)}>
                {busy(r) ? <LoaderCircle size={14} className="spin" /> : (r.review?.score ?? "—")}
              </span>
              <span className="cl-row-main">
                <b>{r.title}</b>
                <small>
                  {r.caller} · {Math.round(r.seconds)} с
                </small>
              </span>
            </button>
          ))}
        </div>

        {call && (
          <article className="cl-doc">
            <header>
              <div>
                <small>
                  {call.caller} · {Math.round(call.seconds)} с
                </small>
                <h2>{call.title}</h2>
              </div>
              {call.review && <span className={"cl-big " + tone(call.review.score)}>{call.review.score ?? "—"}</span>}
            </header>
            <audio controls preload="none" src={call.audio} className="cl-audio" />

            {!call.review && (
              <div className="cl-empty">
                {busy(call) ? (
                  <>
                    <LoaderCircle size={16} className="spin" /> Распознаём речь и разбираем звонок — обычно 10–20
                    секунд…
                  </>
                ) : (
                  <>
                    {call.job?.state === "failed" && (
                      <p className="cl-error">Прошлая попытка не удалась: {call.job.error}</p>
                    )}
                    <button className="button primary" onClick={() => reviewIt(call.id)}>
                      <Sparkles size={16} /> Распознать и разобрать
                    </button>
                  </>
                )}
              </div>
            )}

            {call.review && (
              <>
                <p className="cl-summary">{call.review.summary}</p>
                {call.review.advice && (
                  <p className="cl-advice">
                    <b>Совет диспетчеру:</b> {call.review.advice}
                  </p>
                )}
                <ul className="cl-items">
                  {call.review.items.map((i) => {
                    const Icon = ICON[i.status] || CircleDashed;
                    return (
                      <li key={i.key} className={i.status}>
                        <Icon size={16} />
                        <div>
                          <b>
                            {label[i.key]?.label}{" "}
                            <small>
                              · {LABEL[i.status]} · вес {label[i.key]?.weight}
                            </small>
                          </b>
                          <span>{i.reason}</span>
                          {i.evidence && <q>{i.evidence}</q>}
                        </div>
                      </li>
                    );
                  })}
                </ul>
                <details className="cl-transcript">
                  <summary>Расшифровка ({call.review.stt.model.split("/").pop()})</summary>
                  <p>{call.review.transcript}</p>
                </details>
                <p className="cl-meta">
                  Распознавание {usd(call.review.stt.cost)} · {(call.review.stt.ms / 1000).toFixed(1)} с · разбор{" "}
                  {call.review.review.model.split("/").pop()} {usd(call.review.review.cost)} ·{" "}
                  {(call.review.review.ms / 1000).toFixed(1)} с · балл = 100 × набранный вес / вес применимых пунктов
                </p>
              </>
            )}
          </article>
        )}
      </div>
    </div>
  );
}
