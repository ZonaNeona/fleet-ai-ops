import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Pause, Play, RotateCcw, X, AlertTriangle } from "lucide-react";
import { api } from "../lib";
import type { FEdge, RunState } from "./flow";

/* Общие кирпичи консоли «Под капотом»: уровень объяснения, проигрыватель трасс, таймлайн, JSON. */

export const LevelCtx = createContext(false);
export const useEngineer = () => useContext(LevelCtx);

/** Текст в двух регистрах: «просто» и «для инженера». */
export function Say({ simple, eng }: { simple: ReactNode; eng: ReactNode }) {
  return <>{useEngineer() ? eng : simple}</>;
}

export type Frame = {
  key: string;
  node: string;
  edges?: (string | { id: string; reverse?: boolean; error?: boolean })[];
  status?: "success" | "error" | "retry";
  label: string;
  ms?: number;
  /** сколько показывать кадр, мс */
  hold?: number;
  step?: any;
};

/** Проигрыватель: по кадрам зажигает ноды, пускает частицы, ведёт камеру. */
export function useReplay(frames: Frame[], key: string, autoplay = true) {
  const [pos, setPos] = useState(frames.length);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (autoplay && frames.length) {
      setPos(0);
      setPlaying(true);
    } else {
      setPos(frames.length);
      setPlaying(false);
    }
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!playing) return;
    if (pos >= frames.length) {
      setPlaying(false);
      return;
    }
    const f = frames[pos];
    const t = setTimeout(() => setPos((p) => p + 1), f.hold ?? 1100);
    return () => clearTimeout(t);
  }, [playing, pos, frames]);

  const view = useMemo(() => {
    const states: Record<string, RunState> = {};
    const lit = new Set<string>();
    const pulses: Record<string, { pulse: number; reverse?: boolean; error?: boolean }> = {};
    frames.slice(0, Math.min(pos + 1, frames.length)).forEach((f, i) => {
      const current = i === pos && pos < frames.length;
      states[f.node] = current && playing ? "running" : (f.status ?? "success");
      for (const e of f.edges || []) {
        const id = typeof e === "string" ? e : e.id;
        lit.add(id);
        if (current)
          pulses[id] = {
            pulse: i + 1,
            reverse: typeof e === "string" ? false : e.reverse,
            error: typeof e === "string" ? false : e.error,
          };
      }
    });
    return { states, lit, pulses };
  }, [frames, pos, playing]);

  return {
    pos,
    playing,
    current: pos < frames.length ? frames[pos] : null,
    done: pos >= frames.length,
    play: () => {
      if (pos >= frames.length) setPos(0);
      setPlaying(true);
    },
    pause: () => setPlaying(false),
    seek: (i: number) => {
      setPlaying(false);
      setPos(i);
    },
    ...view,
    /** накладывает состояние проигрывания на рёбра */
    paint: (edges: FEdge[]): FEdge[] =>
      edges.map((e) => ({
        ...e,
        lit: view.lit.has(e.id) || e.lit,
        pulse: view.pulses[e.id]?.pulse,
        reverse: view.pulses[e.id]?.reverse,
        error: view.pulses[e.id]?.error || e.error,
      })),
  };
}

/** Задание AI в очереди: запуск и опрос результата (как в боте и «Спросить AI»). */
export function useJob(
  mode: "rag" | "agent",
  role: string,
  initial = "",
  onStart?: (id: string, prompt: string) => void,
) {
  const [job, setJob] = useState(initial);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  useEffect(() => {
    if (initial) setJob(initial);
  }, [initial]);
  const q = useQuery({
    queryKey: ["under-job", job, role],
    queryFn: () => api("/jobs/" + job),
    enabled: !!job,
    refetchInterval: (q) =>
      ["done", "failed"].includes((q.state.data as any)?.state) ? false : 1000,
  });
  const state: string | undefined = q.data?.state;
  return {
    job,
    prompt,
    state,
    result: state === "done" ? q.data.result : null,
    failed: state === "failed" ? q.data?.result?.error || "Задание завершилось ошибкой" : "",
    busy: pending || (!!job && !["done", "failed"].includes(state || "")),
    error: error || (q.error as any)?.message || "",
    async run(prompt: string) {
      setError("");
      setPending(true);
      setJob("");
      setPrompt(prompt);
      try {
        const j = await api("/under/" + mode, { method: "POST", body: JSON.stringify({ prompt }) });
        setJob(j.id);
        onStart?.(j.id, prompt);
      } catch (e: any) {
        setError(e.message);
      } finally {
        setPending(false);
      }
    },
  };
}

export const ms = (v?: number) =>
  v === undefined || v === null ? "" : v >= 1000 ? (v / 1000).toFixed(1) + " с" : Math.round(v) + " мс";

/** Таймлайн прогона: шаги с реальной длительностью, клик — перемотка. */
export function Timeline({
  frames,
  replay,
  empty,
}: {
  frames: Frame[];
  replay: ReturnType<typeof useReplay>;
  empty?: ReactNode;
}) {
  const max = Math.max(1, ...frames.map((f) => f.ms || 0));
  const total = frames.reduce((a, f) => a + (f.ms || 0), 0);
  return (
    <div className="k-timeline">
      <div className="k-tl-controls">
        {replay.playing ? (
          <button className="k-icon" onClick={replay.pause} aria-label="Пауза">
            <Pause size={15} />
          </button>
        ) : (
          <button
            className="k-icon primary"
            onClick={replay.play}
            disabled={!frames.length}
            aria-label="Проиграть"
          >
            {replay.done && frames.length ? <RotateCcw size={15} /> : <Play size={15} />}
          </button>
        )}
        <div className="k-tl-total">
          <strong>{total ? ms(total) : "—"}</strong>
          <span>{frames.length ? frames.length + " шаг." : "нет прогона"}</span>
        </div>
      </div>
      <div className="k-tl-track">
        {!frames.length && <div className="k-tl-empty">{empty}</div>}
        {frames.map((f, i) => {
          const state =
            i < replay.pos || replay.done ? f.status || "success" : i === replay.pos ? "now" : "todo";
          return (
            <button
              key={f.key}
              className={"k-tl-step " + state}
              onClick={() => replay.seek(i)}
              title={f.label}
            >
              <span className="k-tl-dot">
                {state === "success" ? (
                  <Check size={10} strokeWidth={3} />
                ) : state === "error" ? (
                  <X size={10} strokeWidth={3} />
                ) : state === "retry" ? (
                  <AlertTriangle size={9} strokeWidth={3} />
                ) : (
                  i + 1
                )}
              </span>
              <span className="k-tl-label">{f.label}</span>
              <span className="k-tl-ms">{ms(f.ms)}</span>
              {total > 0 && (
                <span className="k-tl-bar">
                  <i style={{ width: Math.max(4, ((f.ms || 0) / max) * 100) + "%" }} />
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** JSON с подсветкой — для режима инженера. */
export function Json({ value, max = 4000 }: { value: any; max?: number }) {
  let text = typeof value === "string" ? value : JSON.stringify(value, null, 2) ?? "";
  if (text.length > max) text = text.slice(0, max) + "\n…";
  const parts: ReactNode[] = [];
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|\b-?\d+(?:\.\d+)?(?:e[+-]?\d+)?\b|\btrue\b|\bfalse\b|\bnull\b/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const cls = m[1] ? (m[2] ? "k" : "s") : /^-?\d/.test(m[0]) ? "n" : "b";
    parts.push(
      <span key={i++} className={"j-" + cls}>
        {m[1] || m[0]}
      </span>,
    );
    if (m[2]) parts.push(m[2]);
    last = m.index + m[0].length;
  }
  parts.push(text.slice(last));
  return <pre className="k-json">{parts}</pre>;
}

export function Kv({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="k-kv">
      {items
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v], i) => (
          <div key={i}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
    </dl>
  );
}

export function Section({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <section className="k-sec">
      <h4>{title}</h4>
      {children}
    </section>
  );
}
