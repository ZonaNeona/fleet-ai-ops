import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Webhook,
  Clock3,
  Globe,
  Code2,
  ShieldAlert,
  Flag,
  Upload,
  Building2,
  Play,
  LoaderCircle,
  ArrowUpRight,
  Lock,
} from "lucide-react";
import { api, Data, Row } from "../lib";
import { FlowCanvas, type FEdge, type FNode } from "./flow";
import { Frame, Json, Kv, Say, Section, Timeline, ms, useEngineer, useReplay } from "./kit";
import wf1c from "../../n8n/out/1c.json";
import wfYandex from "../../n8n/out/yandex-pro.json";
import wfFines from "../../n8n/out/fines.json";
import wfTele from "../../n8n/out/telematics.json";

type Wf = {
  nodes: { name: string; type: string; position: number[]; parameters: any }[];
  connections: Record<string, { main: { node: string }[][] }>;
};
const WF = { "1c": wf1c, "yandex-pro": wfYandex, fines: wfFines, telematics: wfTele } as unknown as Record<string, Wf>;
export const SOURCES: Record<string, { title: string; what: string }> = {
  "1c": { title: "1С · учёт", what: "Пробег и начисления из справочника ТС и регистра начислений (OData)." },
  "yandex-pro": { title: "Яндекс Про", what: "Выручка водителей по машинам." },
  fines: { title: "Штрафы ГИБДД", what: "Постановления по госномерам." },
  telematics: { title: "Телематика", what: "Пробег по одометру с трекеров." },
};
const STAFF = ["owner", "admin", "finance", "manager"];

/** Иконка/цвет по типу ноды n8n; HTTP-ноды различаем по роли в процессе. */
function meta(n: Wf["nodes"][number]) {
  const url = String(n.parameters?.url || "");
  if (n.type.endsWith(".webhook")) return { icon: Webhook, color: "#a78bfa", tech: "Webhook" };
  if (n.type.endsWith(".scheduleTrigger")) return { icon: Clock3, color: "#a78bfa", tech: "Schedule · cron" };
  if (url.includes("/ingest")) return { icon: Upload, color: "#34d399", tech: "HTTP → ingest" };
  if (url.includes("/snapshot")) return { icon: Building2, color: "#fb923c", tech: "HTTP → источник" };
  if (n.type.endsWith(".httpRequest")) return { icon: Globe, color: "#fb923c", tech: "HTTP Request" };
  if (n.name.startsWith("Ошибка")) return { icon: ShieldAlert, color: "#f43f5e", tech: "Code · error branch" };
  if (n.name === "Готово") return { icon: Flag, color: "#34d399", tech: "Code" };
  return { icon: Code2, color: "#fbbf24", tech: "Code · JS" };
}
const SIMPLE_NODE: Record<string, string> = {
  "Запуск из кабинета": "Кнопка «Запустить» в кабинете будит конвейер.",
  "По расписанию": "Раз в час конвейер запускается сам — без участия людей.",
  "Выбрать активные сессии": "Плановый запуск выбирает, для каких пространств собирать данные.",
  "Контекст запуска": "Проверяем, что запуск подписан системой, а не пришёл извне.",
  "Загрузить источник": "Забираем данные из внешней системы.",
  "Нормализовать данные": "Приводим данные к единому виду и отбрасываем мусор: пустые коды, отрицательные числа.",
  "Подписанный пакет → учёт": "Отправляем пакет в учёт. Без верной подписи его не примут.",
  "Ошибка источника": "Если что-то пошло не так — запуск помечается ошибкой, данные не попадают в учёт.",
  Готово: "Конвейер завершён, сверка обновлена.",
};

export function N8nView({ data, openRow, initialRun }: { data: Data; openRow: (r: Row) => void; initialRun?: string }) {
  const eng = useEngineer();
  const qc = useQueryClient();
  const staff = STAFF.includes(data.session.role);
  const [source, setSource] = useState("1c");
  const [runId, setRunId] = useState(initialRun || "");
  const [selected, setSelected] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const list = useQuery({
    queryKey: ["integrations", data.session.role],
    queryFn: () => api("/integrations"),
    enabled: staff,
    refetchInterval: (q) =>
      ((q.state.data as any)?.runs || []).some((r: any) => ["queued", "running", "pending"].includes(r.status)) ? 1500 : 10000,
  });
  const runs: any[] = (list.data?.runs || []).filter((r: any) => r.source === source);
  useEffect(() => {
    if (initialRun && list.data) {
      const r = list.data.runs.find((x: any) => x.id === initialRun);
      if (r) setSource(r.source);
    }
  }, [initialRun, !!list.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = runs.find((r) => r.id === runId) || runs[0];
  const live = run && ["queued", "running", "pending"].includes(run.status);
  const trace: any[] = run?.data?.trace || [];
  const wf = WF[source];

  const edgesAll: (FEdge & { idx: number })[] = useMemo(
    () =>
      Object.entries(wf.connections).flatMap(([from, c]) =>
        c.main.flatMap((targets, idx) =>
          targets.map((t) => ({
            id: from + "→" + t.node,
            from,
            to: t.node,
            idx,
            dashed: idx === 1,
            danger: idx === 1,
          })),
        ),
      ),
    [wf],
  );
  const frames: Frame[] = useMemo(() => {
    const done = new Set<string>();
    return trace.map((s, i) => {
      const incoming = edgesAll.filter((e) => e.to === s.node && done.has(e.from));
      done.add(s.node);
      return {
        key: s.node + i,
        node: s.node,
        label: s.node,
        ms: s.ms,
        step: s,
        status: s.status === "error" || s.node.startsWith("Ошибка") ? "error" : "success",
        edges: incoming.map((e) => ({ id: e.id, error: e.idx === 1 })),
        hold: 1000,
      };
    });
  }, [trace, edgesAll]);
  const replay = useReplay(frames, (run?.id || "") + ":" + run?.status, true);
  useEffect(() => setSelected(null), [run?.id]);

  const nodes: FNode[] = wf.nodes.map((n) => {
    const m = meta(n);
    const step = trace.find((s) => s.node === n.name);
    const reached = replay.states[n.name];
    return {
      id: n.name,
      x: n.position[0] * 0.9,
      y: n.position[1] * 1.05,
      icon: m.icon,
      color: m.color,
      title: n.name,
      sub: reached && step ? ms(step.ms) + " · " + step.items + " шт" : eng ? m.tech : undefined,
      state: live && n.name === "Запуск из кабинета" ? "running" : reached,
      dim: frames.length > 0 && replay.done && !step,
    };
  });
  const edges = replay.paint(edgesAll).map((e) => (live && e.from === "Запуск из кабинета" ? { ...e, flow: true } : e));

  async function launch() {
    setPending(true);
    setError("");
    try {
      const r = await api("/integrations/run", { method: "POST", body: JSON.stringify({ source }) });
      setRunId(r.id);
      qc.invalidateQueries({ queryKey: ["integrations"] });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setPending(false);
    }
  }

  const node = selected ? wf.nodes.find((n) => n.name === selected) : null;
  const step = selected ? trace.find((s) => s.node === selected) : replay.playing ? replay.current?.step : null;
  const diffs: any[] = (list.data?.diffs || []).filter((d: any) => d.source === source);

  return (
    <div className="k-stage">
      <div className="k-canvas-wrap">
        <div className="k-canvas-head">
          <div className="k-scenarios">
            {Object.entries(SOURCES).map(([id, s]) => {
              const st = list.data?.sources?.find((x: any) => x.id === id);
              return (
                <button
                  key={id}
                  className={source === id ? "active" : ""}
                  onClick={() => {
                    setSource(id);
                    setRunId("");
                  }}
                >
                  <i className={"k-dot " + (st?.status || "")} />
                  {s.title}
                </button>
              );
            })}
          </div>
          <button className="k-btn primary" disabled={!staff || pending || live} onClick={launch}>
            {pending || live ? <LoaderCircle size={15} className="spin" /> : <Play size={15} />}
            {live ? "Выполняется" : "Запустить workflow"}
          </button>
        </div>
        <FlowCanvas
          nodes={nodes}
          edges={edges}
          focus={replay.playing ? replay.current?.node : null}
          selected={selected}
          onSelect={setSelected}
          scene={source + ":" + run?.id + ":" + replay.done}
        />
        {!staff && (
          <div className="k-lock">
            <Lock size={20} />
            <p>Интеграции доступны собственнику, менеджеру и финансисту. Смените роль вверху.</p>
          </div>
        )}
      </div>
      <aside className="k-inspector">
        {(error || list.error) && <div className="k-alert">{error || (list.error as any)?.message}</div>}
        {node ? (
          <>
            <div className="k-ins-head">
              <span className="k-ins-icon" style={{ ["--c" as any]: meta(node).color }}>
                {(() => {
                  const I = meta(node).icon;
                  return <I size={20} />;
                })()}
              </span>
              <div>
                <span className="k-eyebrow">{node.type.replace("n8n-nodes-base.", "n8n · ")}</span>
                <h3>{node.name}</h3>
              </div>
            </div>
            <p className="k-lead">{SIMPLE_NODE[node.name] || meta(node).tech}</p>
            {step && (
              <Kv items={[["Статус", step.status === "success" ? "выполнено" : "ошибка"], ["Время", ms(step.ms)], ["Записей на выходе", step.items]]} />
            )}
            {eng && (
              <Section title="Параметры ноды">
                <Json value={node.parameters?.jsCode || node.parameters} max={1800} />
              </Section>
            )}
            {eng && step?.output?.sample?.length > 0 && (
              <Section title="Пример данных (без ПДн)">
                <Json value={step.output.sample} />
              </Section>
            )}
          </>
        ) : (
          <>
            <span className="k-eyebrow">n8n · реальное исполнение</span>
            <h3 className="k-h">{SOURCES[source].title}</h3>
            <p className="k-lead">
              <Say
                simple={SOURCES[source].what + " Конвейер забирает данные, проверяет их и сверяет с учётом. Повторный запуск не создаёт дублей."}
                eng="Webhook/Schedule → HTTP к источнику → Code: валидация схемы → HMAC-подписанный пакет → транзакционный ingest (идемпотентно по run). Трасса читается из SQLite n8n через loopback-ридер с HMAC."
              />
            </p>
            {run ? (
              <Kv
                items={[
                  ["Статус", live ? "выполняется…" : run.status === "done" ? "завершено" : run.status === "failed" ? "ошибка" : run.status],
                  ["Исполнение n8n", run.execution_id ? "#" + run.execution_id : "ожидается"],
                  ["Строк получено", run.data?.rows],
                  ["Расхождений", run.data?.diffs],
                  ["Время", trace.length ? ms(trace.reduce((a, s) => a + (s.ms || 0), 0)) : ""],
                ]}
              />
            ) : (
              <p className="k-hint">Запусков ещё не было — нажмите «Запустить workflow».</p>
            )}
            {run?.data?.error && <div className="k-alert">{run.data.error}</div>}
            {diffs.length > 0 && (
              <Section title={"Сверка · " + diffs.length + " расхождений"}>
                <div className="k-diffs">
                  {diffs.slice(0, 12).map((d) => (
                    <button
                      key={d.id}
                      onClick={() => {
                        const v = data.vehicle.find((v) => v.id === d.vehicle);
                        if (v) openRow(v);
                      }}
                    >
                      <span>
                        <b>{d.vehicle_code}</b> · {d.field_label}
                        <small>
                          учёт {d.local} · источник {d.external}
                        </small>
                      </span>
                      <ArrowUpRight size={14} />
                    </button>
                  ))}
                </div>
              </Section>
            )}
            {runs.length > 0 && (
              <Section title="История запусков">
                <div className="k-runs">
                  {runs.slice(0, 8).map((r) => (
                    <button key={r.id} className={run?.id === r.id ? "active" : ""} onClick={() => setRunId(r.id)}>
                      <i className={"k-dot " + r.status} />
                      <span>{new Date(r.started).toLocaleTimeString("ru-RU", { timeZone: "Europe/Moscow" })}</span>
                      <small>#{r.execution_id || "—"} · {r.data?.rows ?? 0} стр. · {r.data?.diffs ?? 0} расх.</small>
                    </button>
                  ))}
                </div>
              </Section>
            )}
          </>
        )}
      </aside>
      <Timeline
        frames={frames}
        replay={replay}
        empty={live ? "n8n выполняет workflow — трасса придёт из базы исполнений" : "Запустите workflow — исполнение проиграется по нодам"}
      />
    </div>
  );
}
