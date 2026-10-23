import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  MessageSquareText,
  Binary,
  Radar,
  TextSearch,
  Merge,
  ScrollText,
  Sparkles,
  BadgeCheck,
  FileCheck2,
  Database,
  ShieldAlert,
  FileText,
} from "lucide-react";
import { api, Data } from "../lib";
import { AnswerText } from "../views";
import { FlowCanvas, type FEdge, type FNode, type RunState } from "./flow";
import { Frame, Json, Kv, Say, Section, Timeline, ms, useEngineer, useJob, useReplay } from "./kit";
import { PromptBar } from "./PromptBar";

const SUGGEST = [
  "Какие документы нужны водителю?",
  "Кто согласует расходы на ремонт?",
  "Как вернуть залог?",
  "Как приготовить борщ?",
];

type Def = { id: string; x: number; y: number; icon: any; color: string; title: string; tech: string };
const NODES: Def[] = [
  { id: "q", x: 0, y: 140, icon: MessageSquareText, color: "#a78bfa", title: "Вопрос", tech: "user query" },
  { id: "embedding", x: 185, y: 20, icon: Binary, color: "#c084fc", title: "Смысловой отпечаток", tech: "MiniLM · 384d" },
  { id: "kb", x: 380, y: 140, icon: Database, color: "#60a5fa", title: "База знаний", tech: "kb_chunk · pgvector" },
  { id: "vector", x: 380, y: -60, icon: Radar, color: "#22d3ee", title: "Поиск по смыслу", tech: "HNSW · cosine" },
  { id: "fts", x: 380, y: 340, icon: TextSearch, color: "#38bdf8", title: "Поиск по словам", tech: "GIN · tsvector" },
  { id: "rrf", x: 570, y: 140, icon: Merge, color: "#fbbf24", title: "Слияние и порог", tech: "RRF k=60 · ≥0.38" },
  { id: "prompt", x: 750, y: 140, icon: ScrollText, color: "#f472b6", title: "Контекст", tech: "system + фрагменты" },
  { id: "llm", x: 930, y: 140, icon: Sparkles, color: "#c084fc", title: "Модель", tech: "structured output" },
  { id: "citations", x: 1110, y: 140, icon: BadgeCheck, color: "#34d399", title: "Проверка ссылок", tech: "citations ⊂ найденным" },
  { id: "answer", x: 1290, y: 140, icon: FileCheck2, color: "#34d399", title: "Ответ", tech: "answer + sources" },
];
const EDGES: FEdge[] = [
  { id: "q-embedding", from: "q", to: "embedding", out: "r", in: "l" },
  { id: "embedding-vector", from: "embedding", to: "vector", out: "r", in: "l" },
  { id: "q-fts", from: "q", to: "fts", out: "r", in: "l" },
  { id: "kb-vector", from: "kb", to: "vector", out: "t", in: "b", dashed: true },
  { id: "kb-fts", from: "kb", to: "fts", out: "b", in: "t", dashed: true },
  { id: "vector-rrf", from: "vector", to: "rrf" },
  { id: "fts-rrf", from: "fts", to: "rrf" },
  { id: "rrf-prompt", from: "rrf", to: "prompt" },
  { id: "prompt-llm", from: "prompt", to: "llm" },
  { id: "llm-citations", from: "llm", to: "citations" },
  { id: "citations-answer", from: "citations", to: "answer" },
];
/** Ветка guard — только когда она реально сработала, иначе пунктир режет схему */
const GUARD_EDGE: FEdge = { id: "rrf-answer", from: "rrf", to: "answer", out: "b", in: "b", dashed: true, label: "нет источников" };

const SIMPLE: Record<string, string> = {
  q: "Вопрос своими словами — без ключевых слов и точных формулировок.",
  embedding: "Вопрос превращается в 384 числа — «смысловой отпечаток». У фраз с похожим смыслом отпечатки похожи, даже если слова разные.",
  kb: "Регламенты заранее нарезаны на фрагменты, у каждого есть свой отпечаток. Всё хранится в той же базе, что и учёт.",
  vector: "Ищем фрагменты с самым похожим отпечатком — то есть по смыслу.",
  fts: "Параллельно ищем по словам — на случай точных терминов, номеров и названий.",
  rrf: "Объединяем оба списка и оставляем только достаточно близкие. Если ничего не подошло — честно отвечаем «не нашёл», модель даже не вызывается.",
  prompt: "Модели передаются только найденные фрагменты и строгие правила: отвечать по ним и ставить ссылки.",
  llm: "Модель формулирует ответ. Если основная недоступна — подключается запасная.",
  citations: "Проверяем, что модель сослалась только на реально найденные фрагменты. Иначе ответ отклоняется.",
  answer: "Ответ со ссылками на источники.",
  guard: "Подходящих фрагментов нет — модель не вызывалась, выдумывать нечего.",
};
const ENG: Record<string, string> = {
  q: "POST /api/v1/under/rag → job(kind=ai, mode=rag); ответ читается опросом /api/v1/jobs/{id}.",
  embedding: "fastembed paraphrase-multilingual-MiniLM-L12-v2 (ONNX, CPU) в коротком дочернем процессе; данные не покидают сервер.",
  kb: "kb_doc / kb_chunk: чанкинг по заголовкам ~500 символов с перекрытием; embedding vector(384), tsv tsvector; переиндексация идемпотентна по хешу текста.",
  vector: "ORDER BY embedding <=> :vec LIMIT 2k — индекс HNSW, косинусное расстояние.",
  fts: "tsv @@ websearch_to_tsquery('russian', :q), ранжирование ts_rank_cd, индекс GIN.",
  rrf: "Reciprocal Rank Fusion: score = Σ 1/(60 + rank). FTS без семантической близости не считается доказательством: порог cosine ≥ 0.38.",
  prompt: "Фрагменты и вопрос помечены как недоверенные данные (защита от prompt injection). Ответ — JSON {answer, fields, citations}.",
  llm: "ai.call_chain: qwen3.8-flash → deepseek-flash; откат при 429/5xx/таймауте; стоимость и токены в Usage, дневной бюджет.",
  citations: "citations ⊂ id переданных фрагментов, иначе RuntimeError — ответ не показывается пользователю.",
  answer: "sources = фрагменты, на которые сослалась модель (title, version, url).",
  guard: "accepted = ∅ → ранний возврат без вызова LLM: cost 0, tokens 0.",
};

export function RagView({
  data,
  initialJob,
  initialPrompt,
  onStart,
}: {
  data: Data;
  initialJob?: string;
  initialPrompt?: string;
  onStart?: (id: string, prompt: string) => void;
}) {
  const eng = useEngineer();
  const job = useJob("rag", data.session.role, initialJob, onStart);
  const [selected, setSelected] = useState<string | null>(null);
  const kb = useQuery({ queryKey: ["under-kb"], queryFn: () => api("/under/kb") });
  const r = job.result;
  const trace: any[] = r?.trace || [];
  const guard = trace.some((s) => s.step === "guard");

  const frames: Frame[] = useMemo(() => {
    if (!r) return [];
    const out: Frame[] = [{ key: "q", node: "q", label: "Вопрос", hold: 700 }];
    trace.forEach((s, i) => {
      const base = { key: s.step + i, ms: s.ms, step: s, hold: 1150 };
      if (s.step === "embedding") out.push({ ...base, node: "embedding", label: "Эмбеддинг", edges: ["q-embedding"] });
      else if (s.step === "vector") out.push({ ...base, node: "vector", label: "Вектор", edges: ["embedding-vector", { id: "kb-vector" }] });
      else if (s.step === "fts") out.push({ ...base, node: "fts", label: "Слова", edges: ["q-fts", "kb-fts"] });
      else if (s.step === "rrf") out.push({ ...base, node: "rrf", label: "RRF", edges: ["vector-rrf", "fts-rrf"] });
      else if (s.step === "guard") out.push({ ...base, node: "answer", label: "Нет источников", status: "retry", edges: [{ id: "rrf-answer", error: true }] });
      else if (s.step === "prompt") out.push({ ...base, node: "prompt", label: "Контекст", edges: ["rrf-prompt"] });
      else if (s.step === "fallback") out.push({ ...base, node: "llm", label: "Откат модели", status: "retry", edges: ["prompt-llm"] });
      else if (s.step === "llm") out.push({ ...base, node: "llm", label: "Модель", edges: ["prompt-llm"] });
      else if (s.step === "citations") out.push({ ...base, node: "citations", label: "Ссылки", edges: ["llm-citations"] });
    });
    if (!guard) out.push({ key: "answer", node: "answer", label: "Ответ", edges: ["citations-answer"], hold: 900 });
    return out;
  }, [r]); // eslint-disable-line react-hooks/exhaustive-deps
  const replay = useReplay(frames, job.job + ":" + !!r);
  useEffect(() => setSelected(null), [job.job]);

  const statOf = (id: string): string | undefined => {
    const s = trace.find((x) => x.step === id);
    if (!s || !(replay.states[id] || replay.done)) return undefined;
    if (id === "vector" || id === "fts") return s.output?.hits + " совп. · " + ms(s.ms);
    if (id === "rrf") return "принято " + s.output?.accepted + " из " + (r?.chunks?.length ?? "—");
    if (id === "llm") return (s.tokens || 0) + " ток. · " + ms(s.ms);
    if (id === "embedding") return "384 числа · " + ms(s.ms);
    if (id === "citations") return (s.output?.citations || []).length + " ссылк. верны";
    return ms(s.ms);
  };
  // пока задание в очереди — «живой» конвейер до вектора
  const waiting = job.busy;
  const nodes: FNode[] = NODES.map((n) => {
    let state: RunState | undefined = r ? replay.states[n.id] : undefined;
    if (waiting && n.id === "q") state = "success";
    if (waiting && n.id === "embedding") state = "running";
    if (r && n.id === "kb" && (replay.states.vector || replay.done)) state = "success";
    if (n.id === "answer" && guard && replay.states.answer) state = "retry";
    return {
      ...n,
      title: n.title,
      sub: statOf(n.id) || (eng ? n.tech : undefined),
      state,
      badge: n.id === "kb" ? kb.data?.vectors : undefined,
      size: n.id === "llm" || n.id === "answer" ? "lg" : "md",
      dim: !!r && guard && ["prompt", "llm", "citations"].includes(n.id),
    };
  });
  const edges = replay.paint(guard ? [...EDGES, GUARD_EDGE] : EDGES).map((e) =>
    waiting && e.id === "q-embedding" ? { ...e, flow: true } : e,
  );
  const focusId = selected || (replay.playing ? replay.current?.node : null);
  const info = focusId || (replay.done && r ? "answer" : null);

  return (
    <div className="k-stage">
      <div className="k-canvas-wrap">
        <PromptBar
          busy={job.busy}
          onRun={(p) => job.run(p)}
          suggestions={SUGGEST}
          initial={initialPrompt}
          placeholder="Спросите о правилах парка своими словами…"
          status={job.busy ? "Задание в очереди → воркер считает эмбеддинг локально" : ""}
        />
        <FlowCanvas
          nodes={nodes}
          edges={edges}
          focus={replay.playing ? replay.current?.node : null}
          selected={selected}
          onSelect={setSelected}
          scene={job.job + ":" + replay.done}
        />
      </div>
      <aside className="k-inspector">
        {(job.error || job.failed) && <div className="k-alert">{job.error || job.failed}</div>}
        {!r && !info && <KbIntro kb={kb.data} />}
        {info && <RagStep id={guard && info === "answer" ? "guard" : info} r={r} trace={trace} />}
      </aside>
      <Timeline
        frames={frames}
        replay={replay}
        empty={job.busy ? "Ждём воркер — трасса появится, как только задание выполнится" : "Задайте вопрос — здесь появится реальная трасса с длительностью каждого шага"}
      />
    </div>
  );
}

function KbIntro({ kb }: { kb: any }) {
  return (
    <>
      <span className="k-eyebrow">RAG · от вопроса к доказательству</span>
      <h3 className="k-h">Ответ только по документам</h3>
      <p className="k-lead">
        <Say
          simple="Помощник не «вспоминает» правила — он находит их в базе знаний и показывает, откуда взял ответ. Если в базе ответа нет, так и скажет."
          eng="Гибридный retrieval (pgvector + FTS) с RRF и порогом релевантности, structured output и валидация цитат. Эмбеддинги локально — ПДн не уходят во внешние API."
        />
      </p>
      <div className="k-metrics">
        <div><strong>{kb?.documents?.length ?? "—"}</strong><span>документов</span></div>
        <div><strong>{kb?.vectors ?? "—"}</strong><span>фрагментов</span></div>
        <div><strong>384</strong><span>измерения</span></div>
      </div>
      <Section title="Что лежит в базе">
        <div className="k-docs">
          {kb?.documents?.map((d: any) => (
            <div key={d.id}>
              <FileText size={14} />
              <span>
                {d.title}
                <small>{d.chunks} фрагм. · {d.version} · {d.kind === "public" ? "публичный источник" : "учебный регламент"}</small>
              </span>
              {d.url && <a href={d.url} target="_blank" rel="noreferrer">↗</a>}
            </div>
          ))}
        </div>
      </Section>
      <p className="k-hint">Попробуйте «Как приготовить борщ?» — увидите, как система отказывается отвечать без источников.</p>
    </>
  );
}

function RagStep({ id, r, trace }: { id: string; r: any; trace: any[] }) {
  const eng = useEngineer();
  const def = NODES.find((n) => n.id === id);
  const s = trace.find((x) => x.step === id);
  const chunks: any[] = r?.chunks || [];
  const accepted = new Set((r?.accepted || []).map((c: any) => c.id));
  return (
    <>
      <div className="k-ins-head">
        <span className="k-ins-icon" style={{ ["--c" as any]: def?.color || "#fbbf24" }}>
          {def ? <def.icon size={20} /> : <ShieldAlert size={20} />}
        </span>
        <div>
          <span className="k-eyebrow">{def?.tech || "guard"}</span>
          <h3>{id === "guard" ? "Нет подходящих источников" : def?.title}</h3>
        </div>
      </div>
      <p className="k-lead">{(eng ? ENG : SIMPLE)[id]}</p>
      {!r && <p className="k-hint">Запустите вопрос — здесь появятся реальные данные этого шага.</p>}
      {r && id === "q" && <blockquote className="k-quote">{r.query}</blockquote>}
      {r && id === "embedding" && s && (
        <>
          <VectorBars values={s.output?.preview || []} />
          <Kv items={[["Модель", s.output?.model], ["Размерность", s.output?.dimensions], ["Время", ms(s.ms)]]} />
        </>
      )}
      {r && (id === "vector" || id === "fts" || id === "rrf") && (
        <>
          {s && <Kv items={[["Время", ms(s.ms)], ...(Object.entries(s.output || {}).map(([k, v]) => [k, String(v)]) as any)]} />}
          <Section title={id === "rrf" ? "Итоговый рейтинг" : "Найдено"}>
            <div className="k-chunks">
              {chunks
                .filter((c) => (id === "vector" ? c.vector_rank : id === "fts" ? c.fts_rank : true))
                .sort((a, b) =>
                  id === "vector" ? a.vector_rank - b.vector_rank : id === "fts" ? a.fts_rank - b.fts_rank : b.rrf - a.rrf,
                )
                .map((c) => (
                  <details key={c.id} className={accepted.has(c.id) ? "ok" : ""}>
                    <summary>
                      <span className="k-chunk-title">{c.title}</span>
                      <span className="k-score">
                        <i style={{ width: Math.max(2, (id === "rrf" ? c.rrf * 30 : c.cosine) * 100) + "%" }} />
                      </span>
                      <small>
                        {id === "rrf"
                          ? `RRF ${Number(c.rrf).toFixed(4)}${accepted.has(c.id) ? " · принят" : ""}`
                          : id === "vector"
                            ? `#${c.vector_rank} · cos ${Number(c.cosine).toFixed(3)}`
                            : `#${c.fts_rank}`}
                        {eng && id === "rrf" && ` · vec #${c.vector_rank ?? "—"} · fts #${c.fts_rank ?? "—"} · cos ${Number(c.cosine).toFixed(3)}`}
                      </small>
                    </summary>
                    <p>{c.text}</p>
                  </details>
                ))}
              {!chunks.length && <p className="k-hint">Ничего не найдено.</p>}
            </div>
          </Section>
        </>
      )}
      {r && id === "prompt" && s && (eng ? <Json value={s.output} /> : <Kv items={[["Фрагментов передано", s.output?.chunk_ids?.length]]} />)}
      {r && id === "llm" && (
        <>
          {trace.filter((x) => x.step === "fallback").map((f, i) => (
            <div className="k-alert warn" key={i}>Модель {f.model} не ответила ({f.output?.reason}) — откат на следующую за {ms(f.ms)}</div>
          ))}
          {s && <Kv items={[["Модель", s.model], ["Провайдер", s.output?.provider], ["Токены", s.tokens], ["Стоимость", "$" + Number(s.cost || 0).toFixed(6)], ["Время", ms(s.ms)]]} />}
        </>
      )}
      {r && id === "citations" && s && (
        <>
          <Kv items={[["Ссылки", (s.output?.citations || []).map((n: number) => "ист. " + n).join(", ")], ["Проверка", s.output?.valid ? "пройдена" : "нет"]]} />
          {eng && <p className="k-hint">{s.output?.scope}</p>}
        </>
      )}
      {r && (id === "answer" || id === "guard") && (
        <>
          <div className="k-answer"><AnswerText text={r.answer} /></div>
          {(r.sources || []).map((src: any, i: number) => (
            <a className="k-source" key={i} href={src.url || undefined} target={src.url ? "_blank" : undefined} rel="noreferrer">
              <span>ист. {i + 1}</span>
              {src.title}
              <small>{src.version} · {src.kind === "public" ? "публичный источник" : "учебный регламент"}</small>
            </a>
          ))}
          <Kv items={[["Модель", r.model], ["Токены", r.tokens], ["Стоимость", "$" + Number(r.cost || 0).toFixed(6)], ["Всего", ms(r.ms)]]} />
        </>
      )}
    </>
  );
}

function VectorBars({ values }: { values: number[] }) {
  const max = Math.max(0.0001, ...values.map((v) => Math.abs(v)));
  return (
    <div className="k-vector">
      {values.map((v, i) => (
        <div key={i} title={v.toFixed(4)}>
          <i className={v < 0 ? "neg" : ""} style={{ height: (Math.abs(v) / max) * 50 + "%" }} />
        </div>
      ))}
      <span>…ещё 376 чисел</span>
    </div>
  );
}
