import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Inbox,
  ScanText,
  Tags,
  ListChecks,
  Database,
  UserCheck,
  BookCheck,
  Ban,
  HardDrive,
} from "lucide-react";
import { api, Data } from "../lib";
import { FlowCanvas, type FEdge, type FNode, type RunState } from "./flow";
import { Frame, Kv, Say, Section, Timeline, ms, useEngineer, useReplay } from "./kit";

type Def = { id: string; x: number; y: number; icon: any; color: string; title: string; tech: string };
const NODES: Def[] = [
  { id: "inbox", x: 0, y: 140, icon: Inbox, color: "#a78bfa", title: "Входящий документ", tech: "бот · кабинет · файл" },
  { id: "read", x: 190, y: 140, icon: ScanText, color: "#c084fc", title: "Распознавание", tech: "текстовый слой | vision" },
  { id: "classify", x: 380, y: 140, icon: Tags, color: "#22d3ee", title: "Тип и поля", tech: "fine · invoice · license" },
  { id: "validate", x: 570, y: 140, icon: ListChecks, color: "#fbbf24", title: "Сверка с учётом", tech: "машина · договор · смета · дубль" },
  { id: "ledger", x: 570, y: -70, icon: Database, color: "#60a5fa", title: "Учёт", tech: "PostgreSQL · items / entries" },
  { id: "review", x: 760, y: 330, icon: UserCheck, color: "#f472b6", title: "Решение человека", tech: "interrupt() · Command(resume)" },
  { id: "checkpoint", x: 570, y: 470, icon: HardDrive, color: "#94a3b8", title: "Чекпойнт", tech: "PostgresSaver · schema langgraph" },
  { id: "post", x: 950, y: 140, icon: BookCheck, color: "#34d399", title: "Проводка", tech: "entries · команды домена" },
  { id: "reject", x: 950, y: 470, icon: Ban, color: "#f87171", title: "Отклонено", tech: "без проводки" },
];
const EDGES: FEdge[] = [
  { id: "inbox-read", from: "inbox", to: "read" },
  { id: "read-classify", from: "read", to: "classify" },
  { id: "classify-validate", from: "classify", to: "validate" },
  { id: "ledger-validate", from: "ledger", to: "validate", out: "b", in: "t", dashed: true },
  { id: "validate-post", from: "validate", to: "post", label: "всё сошлось" },
  { id: "validate-review", from: "validate", to: "review", out: "b", in: "l", label: "расхождение" },
  { id: "checkpoint-review", from: "checkpoint", to: "review", out: "r", in: "b", dashed: true },
  { id: "review-post", from: "review", to: "post", out: "r", in: "b", label: "подтвердить" },
  { id: "review-reject", from: "review", to: "reject", out: "b", in: "l", label: "отклонить" },
  { id: "post-ledger", from: "post", to: "ledger", out: "t", in: "r", dashed: true },
];
const SIMPLE: Record<string, string> = {
  inbox: "Водитель присылает фото штрафа в бот, подрядчик — счёт, менеджер загружает права кандидата. Всё попадает в одну очередь.",
  read: "Если в PDF есть текст — читаем его правилами, бесплатно. Фото и сканы читает vision-модель, и её стоимость видна.",
  classify: "Понимаем, что это за документ, и вытаскиваем нужные поля: номер, дату, госномер, сумму.",
  validate: "Сверяем с учётом: есть ли такая машина, кто ездил на ней в день штрафа, укладывается ли счёт в смету, не приходил ли документ раньше.",
  ledger: "Те же данные, что в кабинете: машины, договоры, заявки на ремонт, проводки.",
  review: "Если что-то не сошлось — система останавливается и ждёт человека. Решение можно принять через час или завтра: процесс продолжится с того же места.",
  checkpoint: "Состояние остановленного процесса сохраняется в базе, поэтому его не потерять при перезапуске сервера.",
  post: "Штраф — начисление водителю по договору, счёт СТО — закрытие ремонта и расход машины, права — карточка кандидата на проверку.",
  reject: "Документ возвращается, в учёте ничего не меняется.",
};
const ENG: Record<string, string> = {
  inbox: "POST /api/v1/inbox → Item(kind=inbox) + Job(kind=inbox). Воркер запускает граф коротким подпроцессом: python -m app.inbox_graph run <id> — библиотеки LangGraph не остаются в памяти воркера.",
  read: "pypdf → текстовый слой; иначе pypdfium2 рендерит до 2 страниц в JPEG → VISION_MODEL через общий ai.call: резерв бюджета под advisory lock, стоимость из usage.",
  classify: "Правила: регулярные выражения по типу документа, уверенность = доля обязательных полей. Модель: JSON {kind, confidence, …поля}, лишние ключи отбрасываются.",
  validate: "inbox.run_checks: госномер → vehicle (нормализация латиница→кириллица), contract на дату (start ≤ d < end), ticket в статусе repair и сумма ≤ estimate, дубль по номеру и по source_record из n8n, закрытый период.",
  ledger: "Одна транзакция на шаг; graph state хранит только id документа и решение — сам документ живёт в items.",
  review: "node_review вызывает interrupt(); POST /inbox/{id}/decide ставит Job с decision → app.invoke(Command(resume='approve'|'reject'), thread_id='inbox-<id>').",
  checkpoint: "langgraph-checkpoint-postgres, отдельная схема langgraph (search_path), saver.setup() идемпотентен.",
  post: "Штраф: domain.post(charge) с ключом inbox:<id>. Счёт: domain.command('ticket.complete') от имени сервиса — та же бизнес-логика, что в кабинете. ВУ: command('client.create') → статус review.",
  reject: "node_reject: статус rejected, шаг post = skipped.",
};
const STATUS: Record<string, string> = {
  new: "в очереди",
  reading: "распознаётся",
  checking: "сверка",
  posting: "проводка",
  deciding: "применяется решение",
  review: "ждёт решения",
  mismatch: "расхождение суммы",
  posted: "проведено",
  rejected: "отклонено",
  failed: "ошибка",
};

export function DocsView({ data, openInbox }: { data: Data; openInbox: () => void }) {
  const eng = useEngineer();
  const staff = ["owner", "admin", "finance", "manager", "service"].includes(data.session.role);
  const inbox = useQuery({
    queryKey: ["inbox"],
    queryFn: () => api<any>("/inbox"),
    enabled: staff,
    refetchInterval: (q) =>
      q.state.data?.rows.some((r: any) => ["new", "reading", "checking", "posting", "deciding"].includes(r.status)) ? 1500 : false,
  });
  const rows: any[] = inbox.data?.rows || [];
  const [picked, setPicked] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const doc = rows.find((r) => r.id === picked) || rows.find((r) => ["review", "mismatch"].includes(r.status)) || rows[0];
  const steps: any[] = doc?.steps || [];
  const step = (n: string) => steps.find((s) => s.node === n);

  const frames: Frame[] = useMemo(() => {
    if (!doc) return [];
    const out: Frame[] = [{ key: "inbox", node: "inbox", label: "Документ принят", hold: 600 }];
    const r = step("read");
    if (r) out.push({ key: "read", node: "read", label: "Распознавание", ms: r.ms, edges: ["inbox-read"], status: r.status === "error" ? "error" : "success" });
    const c = step("classify");
    if (c) out.push({ key: "classify", node: "classify", label: "Тип и поля", ms: c.ms, edges: ["read-classify"] });
    const v = step("validate");
    if (v) out.push({ key: "validate", node: "validate", label: "Сверка", ms: v.ms, edges: ["classify-validate", "ledger-validate"], status: v.status === "error" ? "retry" : "success" });
    const rv = step("review");
    if (rv && rv.status !== "skipped") {
      out.push({ key: "review", node: "review", label: rv.status === "active" ? "interrupt()" : "Решение", edges: ["validate-review", "checkpoint-review"], status: rv.status === "active" ? "retry" : "success", hold: 1300 });
    }
    const p = step("post");
    if (doc.status === "rejected") out.push({ key: "reject", node: "reject", label: "Отклонено", edges: ["review-reject"], status: "error" });
    else if (p && p.status !== "skipped")
      out.push({
        key: "post",
        node: "post",
        label: "Проводка",
        ms: p.ms,
        edges: [rv && rv.status !== "skipped" ? "review-post" : "validate-post", "post-ledger"],
        status: p.status === "error" ? "error" : "success",
      });
    return out;
  }, [doc?.id, doc?.version]); // eslint-disable-line react-hooks/exhaustive-deps
  const replay = useReplay(frames, (doc?.id || "") + ":" + (doc?.version || 0));
  useEffect(() => setSelected(null), [doc?.id]);

  const sub = (id: string): string | undefined => {
    const s = step(id);
    if (!s || !(replay.states[id] || replay.done)) return undefined;
    return [ms(s.ms), s.note].filter(Boolean).join(" · ").slice(0, 60);
  };
  const nodes: FNode[] = NODES.map((n) => {
    let state: RunState | undefined = doc ? replay.states[n.id] : undefined;
    if (doc && (n.id === "ledger" || n.id === "checkpoint") && (replay.states.validate || replay.done)) state = n.id === "ledger" ? "success" : state;
    if (n.id === "checkpoint" && replay.states.review) state = "success";
    return {
      ...n,
      sub: sub(n.id) || (eng ? n.tech : undefined),
      state,
      size: n.id === "review" || n.id === "post" ? "lg" : "md",
      dim: !!doc && ((n.id === "reject" && doc.status !== "rejected") || (n.id === "review" && step("review")?.status === "skipped")),
    };
  });
  const edges = replay.paint(EDGES);
  const info = selected || (replay.playing ? replay.current?.node : null);

  return (
    <div className="k-stage">
      <div className="k-canvas-wrap">
        <div className="k-prompt k-docs-bar">
          <select
            className="k-role"
            value={doc?.id || ""}
            onChange={(e) => setPicked(e.target.value)}
            aria-label="Документ"
            disabled={!rows.length}
          >
            {rows.map((r) => (
              <option key={r.id} value={r.id}>
                {r.code} · {r.kind ? inbox.data.kinds[r.kind] : r.name} · {STATUS[r.status] || r.status}
              </option>
            ))}
          </select>
          <button className="k-btn" onClick={openInbox}>
            Открыть «Документы» в кабинете
          </button>
        </div>
        <FlowCanvas
          nodes={nodes}
          edges={edges}
          focus={replay.playing ? replay.current?.node : null}
          selected={selected}
          onSelect={setSelected}
          scene={(doc?.id || "") + ":" + replay.done}
        />
      </div>
      <aside className="k-inspector">
        {!staff && <div className="k-alert">Входящие документы видят сотрудники: переключите роль на собственника, финансиста или менеджера.</div>}
        {!info && <Intro rows={rows} doc={doc} />}
        {info && <StepInfo id={info} doc={doc} fields={inbox.data?.fields} />}
      </aside>
      <Timeline frames={frames} replay={replay} empty="Выберите документ — здесь появится его реальный путь по графу с длительностью шагов" />
    </div>
  );
}

function Intro({ rows, doc }: { rows: any[]; doc: any }) {
  const auto = rows.filter((r) => r.status === "posted" && !r.decided_by).length;
  const hold = rows.filter((r) => ["review", "mismatch"].includes(r.status)).length;
  return (
    <>
      <span className="k-eyebrow">LangGraph · человек в контуре</span>
      <h3 className="k-h">Документ → проверка → проводка</h3>
      <p className="k-lead">
        <Say
          simple="Каждый документ проходит одни и те же шаги. То, что сошлось с учётом, проводится само. Остальное ждёт человека — и система помнит, на каком шаге остановилась."
          eng="StateGraph из шести узлов; условные рёбра после сверки и решения. interrupt() сохраняет состояние в PostgreSQL, Command(resume) продолжает тот же thread_id."
        />
      </p>
      <div className="k-metrics">
        <div><strong>{rows.length}</strong><span>документов</span></div>
        <div><strong>{auto}</strong><span>проведено само</span></div>
        <div><strong>{hold}</strong><span>ждут решения</span></div>
      </div>
      {doc && (
        <Section title={`${doc.code} — сейчас на холсте`}>
          <Kv
            items={[
              ["Статус", STATUS[doc.status] || doc.status],
              ["Как прочитан", doc.engine === "model" ? `модель ${String(doc.model).split("/").pop()} · $${Number(doc.cost || 0).toFixed(4)}` : doc.engine === "rules" ? "правила, без модели" : "—"],
              ["Итог", doc.result || doc.decision || "—"],
            ]}
          />
        </Section>
      )}
      <p className="k-hint">Нажмите на узел — увидите данные этого шага. В кабинете («Документы») можно прислать скан, который прочитает модель, или принять решение по документу в ожидании.</p>
    </>
  );
}

function StepInfo({ id, doc, fields }: { id: string; doc: any; fields?: Record<string, Record<string, string>> }) {
  const eng = useEngineer();
  const def = NODES.find((n) => n.id === id)!;
  const s = doc?.steps?.find((x: any) => x.node === id);
  return (
    <>
      <div className="k-ins-head">
        <span className="k-ins-icon" style={{ ["--c" as any]: def.color }}>
          <def.icon size={20} />
        </span>
        <div>
          <span className="k-eyebrow">{def.tech}</span>
          <h3>{def.title}</h3>
        </div>
      </div>
      <p className="k-lead">{(eng ? ENG : SIMPLE)[id]}</p>
      {s && <Kv items={[["Статус шага", s.status], ["Время", ms(s.ms) || "—"], ["Итог", s.note || "—"]]} />}
      {doc && id === "read" && doc.engine === "model" && (
        <Kv items={[["Модель", doc.model], ["Стоимость", "$" + Number(doc.cost || 0).toFixed(6)], ["Модель видит", doc.summary || "—"]]} />
      )}
      {doc && id === "read" && doc.text && (
        <Section title="Текстовый слой">
          <pre className="k-pre">{doc.text}</pre>
        </Section>
      )}
      {doc && id === "classify" && doc.kind && fields?.[doc.kind] && (
        <Kv items={Object.entries(fields[doc.kind]).map(([k, label]) => [label, doc.values?.[k] || "не найдено"]) as any} />
      )}
      {doc && id === "validate" && (
        <div className="k-checks">
          {(doc.checks || []).map((c: any) => (
            <div key={c.label} className={c.ok ? "ok" : "bad"}>
              <b>{c.ok ? "✓" : "✗"} {c.label}</b>
              <small>{c.detail}</small>
            </div>
          ))}
        </div>
      )}
      {doc && (id === "review" || id === "post" || id === "reject") && (
        <Kv items={[["Решение", doc.decision || "—"], ["Результат", doc.result || "—"], ["Кто решил", doc.decided_by || (doc.status === "posted" ? "автоматически" : "—")]]} />
      )}
    </>
  );
}
