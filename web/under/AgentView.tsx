import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  MessageSquareText,
  Zap,
  BrainCircuit,
  Wallet,
  CarFront,
  ChartNoAxesCombined,
  FileText,
  BookOpen,
  TicketPlus,
  FileCheck2,
  ClipboardCheck,
  CheckCircle2,
  Lock,
  Handshake,
  ListTodo,
} from "lucide-react";
import { api, Data } from "../lib";
import { AnswerText } from "../views";
import { FlowCanvas, type FEdge, type FNode, type RunState } from "./flow";
import { Frame, Json, Kv, Say, Section, Timeline, ms, useEngineer, useJob, useReplay } from "./kit";
import { PromptBar } from "./PromptBar";

const SUGGEST = [
  "Сколько я должен?",
  "Какие машины в ремонте дольше недели?",
  "Какие 3 машины дают самый низкий результат и почему?",
  "Стучит подвеска. Подготовь заявку по моей машине.",
  "Где зависли кандидаты в найме водителей?",
];

const TOOLS = [
  { id: "get_balance", icon: Wallet, color: "#34d399", title: "Баланс и долг", what: "Начисления, платежи и просрочка — только по доступным роли договорам." },
  { id: "list_vehicles", icon: CarFront, color: "#60a5fa", title: "Автомобили", what: "Список машин роли с фильтром по статусу и дням в ремонте." },
  { id: "vehicle_economics", icon: ChartNoAxesCombined, color: "#fbbf24", title: "Экономика авто", what: "Доход, расходы и результат по машине или N худших." },
  { id: "find_contract", icon: FileText, color: "#a78bfa", title: "Договоры", what: "Поиск договоров, доступных роли." },
  { id: "search_knowledge", icon: BookOpen, color: "#22d3ee", title: "Регламенты", what: "Гибридный поиск RAG по базе знаний." },
  { id: "create_ticket", icon: TicketPlus, color: "#f472b6", title: "Черновик заявки", what: "Только готовит черновик — создать заявку может лишь человек кнопкой «Подтвердить»." },
  { id: "crm_pipeline", icon: Handshake, color: "#fb923c", title: "Битрикс24: воронки", what: "Найм водителей и прокат по стадиям, зависшие сделки, новые лиды, расхождения оплат с учётом." },
  { id: "crm_task", icon: ListTodo, color: "#f472b6", title: "Черновик задачи", what: "Готовит задачу менеджеру в Битрикс24 — создаётся только после подтверждения человеком." },
  { id: "get_signals", icon: Zap, color: "#ef4444", title: "Сделать сейчас", what: "Правила над учётом, сервисом, Битрикс24 и звонками: что требует человека сегодня и следующее действие." },
];

/** Зеркало app/agent.py → tools_for(role): права проверяются на сервере, здесь — для наглядности. */
function allowed(role: string) {
  const s = new Set(["list_vehicles", "find_contract", "search_knowledge"]);
  if (["owner", "admin", "finance", "driver", "client", "investor"].includes(role)) {
    s.add("get_balance");
    s.add("vehicle_economics");
  }
  if (["manager", "driver", "client", "service", "owner", "admin"].includes(role)) s.add("create_ticket");
  if (["owner", "admin", "manager", "finance"].includes(role)) {
    s.add("crm_pipeline");
    s.add("crm_task");
    s.add("get_signals");
  }
  return s;
}

const Y0 = 200;
const toolY = (i: number) => Y0 + (i - (TOOLS.length - 1) / 2) * 100;

const ENGINE: Record<string, string> = {
  rules: "Быстрый ответ без модели",
  kb: "База знаний с цитатами",
  hermes: "Hermes Agent через MCP",
  model: "Встроенный цикл с инструментами",
};

export function AgentView({
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
  const role = data.session.role;
  const job = useJob("agent", role, initialJob, onStart);
  const [selected, setSelected] = useState<string | null>(null);
  const r = job.result;
  const trace: any[] = r?.trace || [];
  const can = allowed(role);
  useEffect(() => setSelected(null), [job.job]);

  const frames: Frame[] = useMemo(() => {
    if (!r) return [];
    const out: Frame[] = [{ key: "q", node: "q", label: "Вопрос", hold: 700 }];
    let returning: string[] = [];
    let round = 0;
    trace.forEach((s, i) => {
      if (s.step === "llm" || s.step === "fallback") {
        round += s.step === "llm" ? 1 : 0;
        out.push({
          key: "m" + i,
          node: "model",
          label: s.step === "fallback" ? "Откат модели" : round === 1 ? "Модель решает" : "Модель · раунд " + round,
          ms: s.ms,
          step: s,
          status: s.step === "fallback" ? "retry" : "success",
          edges: returning.length ? returning.map((t) => ({ id: "model-" + t, reverse: true })) : ["q-model"],
          hold: 1300,
        });
        returning = [];
      } else if (s.step === "tool") {
        out.push({
          key: "t" + i,
          node: "tool:" + s.title,
          label: s.title,
          ms: s.ms,
          step: s,
          status: s.status === "success" ? "success" : "error",
          edges: [{ id: "model-" + s.title, error: s.status !== "success" }],
          hold: 1200,
        });
        returning.push(s.title);
      }
    });
    out.push({ key: "answer", node: "answer", label: "Ответ", edges: ["model-answer"], hold: 900 });
    if (r.drafts?.length) out.push({ key: "draft", node: "draft", label: "Черновик", edges: [draftTool(r) + "-draft"], hold: 900 });
    return out;
  }, [r]); // eslint-disable-line react-hooks/exhaustive-deps
  const replay = useReplay(frames, job.job + ":" + !!r);

  const calls = (tool: string) => trace.filter((s) => s.step === "tool" && s.title === tool);
  const seen = new Set(frames.slice(0, replay.done ? frames.length : replay.pos + 1).map((f) => f.node));
  const order: Record<string, number[]> = {};
  frames.forEach((f, i) => {
    if (f.node.startsWith("tool:")) (order[f.node.slice(5)] ||= []).push(frames.slice(0, i + 1).filter((x) => x.node.startsWith("tool:")).length);
  });

  const nodes: FNode[] = [
    { id: "q", x: 0, y: Y0, icon: MessageSquareText, color: "#a78bfa", title: "Вопрос", sub: eng ? "role=" + role : data.session.roles[role] },
    {
      id: "model", x: 270, y: Y0 - 6, icon: BrainCircuit, color: "#22d3ee", size: "lg", title: "Модель",
      sub: eng ? "tool calling · ≤4 раунда" : "выбирает инструменты",
      badge: r ? trace.filter((s) => s.step === "llm").length + "×" : undefined,
    },
    ...TOOLS.map((t, i): FNode => {
      const used = seen.has("tool:" + t.id);
      const denied = calls(t.id).some((c) => c.status !== "success");
      let state: RunState | undefined = replay.states["tool:" + t.id];
      if (!can.has(t.id) && !state) state = "locked";
      return {
        id: "tool:" + t.id, x: 600, y: toolY(i), icon: t.icon, color: t.color, size: "sm",
        title: eng ? t.id : t.title,
        sub: used ? ms(calls(t.id)[0]?.ms) + (denied ? " · отказ" : "") : !can.has(t.id) ? "нет доступа у роли" : eng ? t.title : undefined,
        state,
        badge: used ? order[t.id]?.join(",") : undefined,
        dim: !can.has(t.id) || (!!r && !used && replay.done),
      };
    }),
    {
      id: "answer", x: 270, y: Y0 + 330, icon: FileCheck2, color: "#34d399", title: "Ответ",
      sub: r && seen.has("answer") ? (r.tokens || 0) + " ток. · $" + Number(r.cost || 0).toFixed(5) : undefined,
      state: replay.states.answer,
    },
  ];
  if (r?.drafts?.length)
    nodes.push({ id: "draft", x: 880, y: toolY(TOOLS.findIndex((t) => t.id === draftTool(r))), icon: ClipboardCheck, color: "#f472b6", title: "Ждёт подтверждения", sub: "черновик · 10 мин", state: replay.states.draft ? "retry" : undefined });

  const edges: FEdge[] = [
    { id: "q-model", from: "q", to: "model" },
    ...TOOLS.map((t) => ({ id: "model-" + t.id, from: "model", to: "tool:" + t.id, dashed: !can.has(t.id) })),
    { id: "model-answer", from: "model", to: "answer", out: "b" as const, in: "t" as const },
    ...(r?.drafts?.length ? [{ id: draftTool(r) + "-draft", from: "tool:" + draftTool(r), to: "draft", label: "человек решает" }] : []),
  ];
  const painted = replay.paint(edges).map((e) => (job.busy && e.id === "q-model" ? { ...e, flow: true } : e));
  if (job.busy) {
    nodes[0].state = "success";
    nodes[1].state = "running";
  }
  const info = selected || (replay.playing ? replay.current?.node : null) || (replay.done && r ? "answer" : null);

  return (
    <div className="k-stage">
      <div className="k-canvas-wrap">
        <PromptBar
          busy={job.busy}
          onRun={(p) => job.run(p)}
          suggestions={SUGGEST}
          initial={initialPrompt}
          placeholder="Поручите задачу помощнику…"
          status={job.busy ? "Задание в очереди → модель выбирает инструменты" : ""}
        />
        <FlowCanvas
          nodes={nodes}
          edges={painted}
          focus={replay.playing ? replay.current?.node : null}
          selected={selected}
          onSelect={setSelected}
          scene={job.job + ":" + replay.done + ":" + role}
        />
      </div>
      <aside className="k-inspector">
        {(job.error || job.failed) && <div className="k-alert">{job.error || job.failed}</div>}
        {!info && <Permissions data={data} can={can} />}
        {info === "q" && (
          <>
            <span className="k-eyebrow">Вопрос</span>
            <h3 className="k-h">{data.session.roles[role]}</h3>
            {r ? <blockquote className="k-quote">{r.query || job.prompt || initialPrompt || "—"}</blockquote> : <p className="k-lead">Задайте вопрос в строке над схемой.</p>}
            <p className="k-hint">
              <Say simple="Роль закрепляется за заданием на сервере — её нельзя «подменить» текстом вопроса." eng="role пишется в job.data при постановке и не берётся из промпта; инструменты строятся tools_for(role)." />
            </p>
          </>
        )}
        {info === "model" && (
          <>
            <span className="k-eyebrow">LLM · tool calling</span>
            <h3 className="k-h">Модель</h3>
            <p className="k-lead">
              <Say
                simple="Модель не имеет доступа к базе. Она лишь просит: «дай мне баланс водителя» — а данные выдаёт код, проверив права."
                eng="OpenAI-совместимый tools API; схемы аргументов — Pydantic → JSON Schema; каждый раунд — отдельный вызов call_chain с откатом на резервную модель."
              />
            </p>
            {trace.filter((s) => s.step === "llm" || s.step === "fallback").map((s, i) => (
              <div className={"k-call " + (s.step === "fallback" ? "warn" : "")} key={i}>
                <b>{s.step === "fallback" ? "Откат: " + (s.output?.reason || "") : "Раунд " + (i + 1)}</b>
                <Kv items={[["Модель", s.model], ["Токены", s.tokens], ["Стоимость", s.cost ? "$" + Number(s.cost).toFixed(6) : ""], ["Время", ms(s.ms)]]} />
              </div>
            ))}
          </>
        )}
        {info?.startsWith("tool:") && <ToolInfo id={info.slice(5)} calls={calls(info.slice(5))} can={can.has(info.slice(5))} role={data.session.roles[role]} />}
        {(info === "answer" || info === "draft") && r && (
          <>
            <span className="k-eyebrow">Результат</span>
            <div className="k-answer"><AnswerText text={r.answer} /></div>
            {(r.sources || []).map((s: any, i: number) => (
              <a className="k-source" key={i} href={s.url || undefined} target={s.url ? "_blank" : undefined} rel="noreferrer">
                <span>ист.</span>
                {s.title}
              </a>
            ))}
            <Drafts drafts={r.drafts || []} />
            <Kv items={[["Ответил", ENGINE[r.engine] || "Встроенный цикл"], ["Модель", r.model], ["Токены", r.tokens], ["Стоимость", "$" + Number(r.cost || 0).toFixed(6)], ["Вызовов инструментов", trace.filter((s) => s.step === "tool").length]]} />
            {r.engine === "rules" && <p className="k-hint">Частый вопрос: ответ собран из инструментов без модели — бесплатно и не тратит лимит.</p>}
          </>
        )}
      </aside>
      <Timeline
        frames={frames}
        replay={replay}
        empty={job.busy ? "Модель думает — трасса появится, как только задание выполнится" : "Поручите задачу — здесь появится каждый вызов модели и инструментов"}
      />
    </div>
  );
}

function Permissions({ data, can }: { data: Data; can: Set<string> }) {
  return (
    <>
      <span className="k-eyebrow">Агент с инструментами</span>
      <h3 className="k-h">От вопроса к действию</h3>
      <p className="k-lead">
        <Say
          simple="Помощник сам решает, какие данные ему нужны, но получает только то, что разрешено вашей роли. Ничего не меняет без вашего подтверждения."
          eng="Агентный цикл с ролевым набором инструментов; авторизация — в коде инструментов, не в промпте. Запись только через черновик + явное подтверждение (human-in-the-loop)."
        />
      </p>
      <Section title={"Инструменты роли «" + data.session.roles[data.session.role] + "»"}>
        <div className="k-perms">
          {TOOLS.map((t) => (
            <div key={t.id} className={can.has(t.id) ? "" : "off"}>
              {can.has(t.id) ? <t.icon size={15} /> : <Lock size={15} />}
              <span>
                <code>{t.id}</code>
                <small>{t.what}</small>
              </span>
            </div>
          ))}
        </div>
      </Section>
      <p className="k-hint">Смените роль вверху и задайте тот же вопрос — замки на схеме и ответ изменятся.</p>
    </>
  );
}

function ToolInfo({ id, calls, can, role }: { id: string; calls: any[]; can: boolean; role: string }) {
  const eng = useEngineer();
  const t = TOOLS.find((x) => x.id === id)!;
  return (
    <>
      <div className="k-ins-head">
        <span className="k-ins-icon" style={{ ["--c" as any]: t.color }}>
          <t.icon size={20} />
        </span>
        <div>
          <span className="k-eyebrow">инструмент</span>
          <h3><code>{id}</code></h3>
        </div>
      </div>
      <p className="k-lead">{t.what}</p>
      {!can && <div className="k-alert">Роль «{role}» не получает этот инструмент — модель о нём даже не знает.</div>}
      {!calls.length && can && <p className="k-hint">В этом прогоне модель не вызывала инструмент.</p>}
      {calls.map((c, i) => (
        <div className={"k-call " + (c.status === "success" ? "" : "err")} key={i}>
          <b>
            Вызов {i + 1} · {c.status === "success" ? "выполнен" : "отклонён"} · {ms(c.ms)}
          </b>
          {eng ? (
            <>
              <small>arguments</small>
              <Json value={c.arguments} />
              <small>result</small>
              <Json value={c.output} max={2500} />
            </>
          ) : (
            <p>
              {c.status === "success"
                ? id === "search_knowledge"
                  ? "Найдено фрагментов: " + (c.output?.sources?.length ?? 0)
                  : id === "create_ticket" || id === "crm_task"
                    ? "Подготовлен черновик — ещё ничего не создано."
                    : "Код вернул данные, доступные роли «" + c.role + "»."
                : c.output?.error}
            </p>
          )}
        </div>
      ))}
    </>
  );
}

function draftTool(r: any) {
  return r?.drafts?.[0]?.action === "crm.task" ? "crm_task" : "create_ticket";
}

function Drafts({ drafts }: { drafts: any[] }) {
  const [status, setStatus] = useState<Record<string, string>>({});
  const q = useQueryClient();
  async function confirm(d: any) {
    setStatus((v) => ({ ...v, [d.id]: "…" }));
    try {
      const r = await api("/under/drafts/" + d.id + "/confirm", { method: "POST", body: "{}" });
      setStatus((v) => ({ ...v, [d.id]: (d.action === "crm.task" ? "Создана задача " : "Создана заявка ") + r.code }));
      q.invalidateQueries({ queryKey: ["bootstrap"] });
    } catch (e: any) {
      setStatus((v) => ({ ...v, [d.id]: e.message }));
    }
  }
  return (
    <>
      {drafts.map((d) => {
        const ok = status[d.id]?.startsWith("Создана");
        return (
          <div className={"k-draft " + (ok ? "ok" : "")} key={d.id}>
            <span className="k-eyebrow">{ok ? "Создано" : "Требует подтверждения человека"}</span>
            <strong>{d.payload?.title}</strong>
            <p>{d.action === "crm.task" ? "Задача в Битрикс24" : d.vehicle_code} · {d.payload?.description}</p>
            <button className="k-btn primary wide" disabled={!!status[d.id] && status[d.id] !== "" && (ok || status[d.id] === "…")} onClick={() => confirm(d)}>
              <CheckCircle2 size={15} />
              {ok ? status[d.id] : d.action === "crm.task" ? "Подтвердить задачу в Битрикс24" : "Подтвердить создание заявки"}
            </button>
            {status[d.id] && !ok && status[d.id] !== "…" && <p className="k-alert">{status[d.id]}</p>}
          </div>
        );
      })}
    </>
  );
}
