import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Check,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleX,
  FileScan,
  FileText,
  Globe,
  IdCard,
  LoaderCircle,
  Receipt,
  Sparkles,
  Upload,
  Workflow,
  X,
} from "lucide-react";
import { api, Data, Row, rub } from "./lib";
import "./inbox.css";

type Step = { node: string; label: string; status: string; ms: number | null; note: string };
type Check = { label: string; ok: boolean; detail: string };
type Doc = Row & {
  source: string;
  name: string;
  status: string;
  kind: string | null;
  values: Record<string, string | null>;
  checks: Check[];
  steps: Step[];
  links: Record<string, string>;
  text?: string;
  file?: string;
  engine?: string;
  model?: string;
  cost?: string;
  confidence?: number;
  decision?: string;
  result?: string;
  summary?: string;
  created: string;
};
type Inbox = {
  rows: Doc[];
  steps: [string, string][];
  kinds: Record<string, string>;
  fields: Record<string, Record<string, string>>;
  model_left: number;
  can_decide: boolean;
};

const BUSY = ["new", "reading", "checking", "posting", "deciding"];
const STATUS: Record<string, [string, string]> = {
  new: ["В очереди", "wait"],
  reading: ["Распознаётся", "wait"],
  checking: ["Сверка", "wait"],
  posting: ["Проводка", "wait"],
  deciding: ["Применяется решение", "wait"],
  review: ["Ждёт решения", "hold"],
  mismatch: ["Расхождение суммы", "hold"],
  posted: ["Проведено", "ok"],
  rejected: ["Отклонено", "off"],
  failed: ["Ошибка", "bad"],
};
const KIND_ICON: Record<string, any> = { fine: Receipt, invoice: FileText, license: IdCard, other: FileScan };
const SOURCE: Record<string, [any, string]> = {
  bot: [Bot, "из Telegram-бота"],
  web: [Globe, "загружен в кабинете"],
  sample: [Sparkles, "пример со стенда"],
};
const LINKS: [string, string, keyof Data][] = [
  ["vehicle", "Машина", "vehicle"],
  ["contract", "Договор", "contract"],
  ["ticket", "Заявка на ремонт", "ticket"],
  ["client", "Кандидат", "client"],
];

export function InboxPage({
  data,
  open,
  toast,
  underGraph,
}: {
  data: Data;
  open: (row: Row) => void;
  toast: (m: string) => void;
  underGraph: (doc: string) => void;
}) {
  const q = useQueryClient();
  const [only, setOnly] = useState("all");
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const inbox = useQuery({
    queryKey: ["inbox"],
    queryFn: () => api<Inbox>("/inbox"),
    refetchInterval: (query) =>
      query.state.data?.rows.some((r) => BUSY.includes(r.status)) ? 1500 : false,
  });
  const rows = useMemo(() => {
    const all = inbox.data?.rows || [];
    if (only === "hold") return all.filter((r) => ["review", "mismatch"].includes(r.status));
    if (only === "posted") return all.filter((r) => r.status === "posted");
    if (only === "rejected") return all.filter((r) => ["rejected", "failed"].includes(r.status));
    return all;
  }, [inbox.data, only]);
  const doc = rows.find((r) => r.id === picked) || rows[0];

  const refresh = () => {
    q.invalidateQueries({ queryKey: ["inbox"] });
    q.invalidateQueries({ queryKey: ["bootstrap"] });
  };
  const send = async (label: string, body: object) => {
    setBusy(label);
    try {
      const created = await api<Doc>("/inbox", { method: "POST", body: JSON.stringify(body) });
      setPicked(created.id);
      setOnly("all");
      refresh();
    } catch (e: any) {
      toast(e.message);
    } finally {
      setBusy("");
    }
  };
  const upload = async (f: File) => {
    const form = new FormData();
    form.append("file", f);
    setBusy("upload");
    try {
      const stored = await api<Row>("/files", { method: "POST", body: form });
      await send("upload", { file: stored.id });
    } catch (e: any) {
      toast(e.message);
      setBusy("");
    }
  };
  const decide = async (approve: boolean) => {
    if (!doc) return;
    setBusy(approve ? "approve" : "reject");
    try {
      await api(`/inbox/${doc.id}/decide`, { method: "POST", body: JSON.stringify({ approve }) });
      refresh();
    } catch (e: any) {
      toast(e.message);
    } finally {
      setBusy("");
    }
  };

  if (inbox.error) return <div className="error">{(inbox.error as Error).message}</div>;
  if (!inbox.data) return <div className="ib-loading"><LoaderCircle className="spin" /> Загружаем входящие…</div>;
  const counts = {
    hold: inbox.data.rows.filter((r) => ["review", "mismatch"].includes(r.status)).length,
    posted: inbox.data.rows.filter((r) => r.status === "posted").length,
  };

  return (
    <div className="ib">
      <div className="ib-intro">
        <div>
          <b>Водители и подрядчики присылают фото и PDF</b> — постановления ГИБДД, счета СТО, права кандидатов.
          Система распознаёт документ, сверяет его с учётом и проводит сама, если всё сошлось. Остальное — на
          решение человеку.
        </div>
        <button className="button ghost" onClick={() => underGraph(doc?.id || "")}>
          <Workflow size={16} /> Граф под капотом
        </button>
      </div>

      <div className="list-toolbar ib-toolbar">
        <div className="tabs">
          {[
            ["all", "Все"],
            ["hold", `Ждут решения · ${counts.hold}`],
            ["posted", `Проведены · ${counts.posted}`],
            ["rejected", "Отклонены"],
          ].map(([id, label]) => (
            <button key={id} className={only === id ? "active" : ""} onClick={() => setOnly(id)}>
              {label}
            </button>
          ))}
        </div>
        <div className="ib-add">
          <button
            className="button secondary"
            disabled={!!busy || inbox.data.model_left === 0}
            onClick={() => send("scan", { sample: "fine_scan" })}
            title="Скан рисуется заново и читается vision-моделью — это платный вызов"
          >
            {busy === "scan" ? <LoaderCircle size={16} className="spin" /> : <FileScan size={16} />}
            Скан штрафа · модель ({inbox.data.model_left})
          </button>
          <button className="button secondary" disabled={!!busy} onClick={() => send("invoice", { sample: "invoice" })}>
            <FileText size={16} /> Счёт СТО
          </button>
          <button className="button secondary" disabled={!!busy} onClick={() => send("license", { sample: "license" })}>
            <IdCard size={16} /> ВУ кандидата
          </button>
          <button className="button primary" disabled={!!busy} onClick={() => file.current?.click()}>
            {busy === "upload" ? <LoaderCircle size={16} className="spin" /> : <Upload size={16} />}
            Свой файл
          </button>
          <input
            ref={file}
            type="file"
            hidden
            accept=".pdf,.png,.jpg,.jpeg"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) upload(f);
            }}
          />
        </div>
      </div>

      <div className="ib-grid">
        <div className="ib-list">
          {rows.map((r) => {
            const Icon = KIND_ICON[r.kind || "other"] || FileScan;
            const [label, tone] = STATUS[r.status] || [r.status, "wait"];
            const [Src] = SOURCE[r.source] || SOURCE.web;
            return (
              <button key={r.id} className={"ib-row" + (doc?.id === r.id ? " active" : "")} onClick={() => setPicked(r.id)}>
                <span className="ib-row-icon">
                  <Icon size={18} />
                </span>
                <span className="ib-row-main">
                  <span className="ib-row-top">
                    <small>{r.code}</small>
                    <Src size={12} />
                  </span>
                  <b>{r.kind ? inbox.data!.kinds[r.kind] : r.name || "Документ"}</b>
                  <span className="muted">
                    {[r.values?.plate, r.values?.amount && rub(r.values.amount)].filter(Boolean).join(" · ") || r.name}
                  </span>
                </span>
                <span className={"ib-pill " + tone}>
                  {BUSY.includes(r.status) && <LoaderCircle size={11} className="spin" />}
                  {label}
                </span>
              </button>
            );
          })}
          {!rows.length && <div className="ib-empty">Здесь пока пусто</div>}
        </div>

        {doc && (
          <article className="ib-doc">
            <header>
              <div>
                <small>
                  {doc.code} · {(SOURCE[doc.source] || SOURCE.web)[1]} ·{" "}
                  {new Date(doc.created).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                </small>
                <h2>{doc.kind ? inbox.data.kinds[doc.kind] : doc.name || "Документ"}</h2>
                {doc.summary && <p className="muted">Модель: «{doc.summary}»</p>}
              </div>
              <span className={"ib-pill big " + (STATUS[doc.status] || ["", "wait"])[1]}>
                {(STATUS[doc.status] || [doc.status])[0]}
              </span>
            </header>

            <ol className="ib-steps">
              {inbox.data.steps.map(([node, label]) => {
                const s = doc.steps.find((x) => x.node === node);
                const st = s?.status || (doc.status === "rejected" && node === "post" ? "skipped" : "todo");
                const Icon =
                  st === "done" ? CircleCheck : st === "error" ? CircleAlert : st === "active" ? CircleDashed : st === "skipped" ? X : CircleDashed;
                return (
                  <li key={node} className={st}>
                    <Icon size={16} />
                    <b>{label}</b>
                    {s?.ms != null && <small>{s.ms < 1000 ? `${s.ms} мс` : `${(s.ms / 1000).toFixed(1)} с`}</small>}
                    {s?.note && <span>{s.note}</span>}
                  </li>
                );
              })}
            </ol>

            {(doc.status === "review" || doc.status === "mismatch") && (
              <div className="ib-decide">
                <div>
                  <b>Нужно решение человека.</b> Запуск графа остановлен на шаге «Решение человека» и сохранён в
                  PostgreSQL; кнопка продолжит тот же запуск.
                </div>
                {inbox.data.can_decide ? (
                  <div className="ib-decide-actions">
                    <button className="button primary" disabled={!!busy} onClick={() => decide(true)}>
                      {busy === "approve" ? <LoaderCircle size={16} className="spin" /> : <Check size={16} />}
                      Подтвердить и провести
                    </button>
                    <button className="button secondary" disabled={!!busy} onClick={() => decide(false)}>
                      <X size={16} /> Отклонить
                    </button>
                  </div>
                ) : (
                  <span className="muted">Решает финансист, менеджер или собственник.</span>
                )}
              </div>
            )}
            {(doc.result || doc.decision) && !["review", "mismatch"].includes(doc.status) && (
              <div className={"ib-result " + (STATUS[doc.status] || ["", ""])[1]}>
                {doc.decision}
                {doc.result && <> · <b>{doc.result}</b></>}
              </div>
            )}

            <div className="ib-cols">
              <section>
                <h3>Поля</h3>
                {doc.kind && doc.kind !== "other" ? (
                  <dl className="ib-fields">
                    {Object.entries(inbox.data.fields[doc.kind] || {}).map(([k, label]) => (
                      <div key={k}>
                        <dt>{label}</dt>
                        <dd className={doc.values?.[k] ? "" : "muted"}>{doc.values?.[k] || "не найдено"}</dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p className="muted">{BUSY.includes(doc.status) ? "Документ ещё читается…" : "Тип не распознан."}</p>
                )}
                <p className="ib-engine muted">
                  {doc.engine === "model"
                    ? `Прочитано моделью ${doc.model?.split("/").pop()} · $${Number(doc.cost || 0).toFixed(4)} · уверенность ${doc.confidence}`
                    : doc.engine === "rules"
                      ? "Текстовый слой прочитан правилами — без модели и бесплатно"
                      : ""}
                </p>
              </section>
              <section>
                <h3>Сверка с учётом</h3>
                {doc.checks?.length ? (
                  <ul className="ib-checks">
                    {doc.checks.map((c) => (
                      <li key={c.label} className={c.ok ? "ok" : "bad"}>
                        {c.ok ? <CircleCheck size={15} /> : <CircleX size={15} />}
                        <span>
                          <b>{c.label}</b>
                          <small>{c.detail}</small>
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">Проверки появятся после распознавания.</p>
                )}
                <div className="ib-links">
                  {LINKS.map(([key, label, kind]) => {
                    const row = (data[kind] as Row[] | undefined)?.find((x) => x.id === doc.links?.[key]);
                    return row ? (
                      <button key={key} className="button ghost" onClick={() => open(row)}>
                        {label}: {row.code}
                      </button>
                    ) : null;
                  })}
                </div>
              </section>
            </div>

            <section className="ib-source">
              <h3>Оригинал</h3>
              {doc.file ? (
                <a href={`/api/v1/files/${doc.file}`} target="_blank" rel="noopener">
                  <img src={`/api/v1/files/${doc.file}`} alt="Оригинал документа" onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />
                  Открыть файл
                </a>
              ) : (
                <pre>{doc.text}</pre>
              )}
            </section>
          </article>
        )}
      </div>
    </div>
  );
}
