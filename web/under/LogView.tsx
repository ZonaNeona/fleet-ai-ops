import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { api, Data } from "../lib";
import { Kv, Say, Section, ms, useEngineer } from "./kit";
import { SOURCES } from "./N8nView";

const TYPE: Record<string, [string, string]> = {
  ai: ["AI", "ai"],
  telegram: ["BOT", "bot"],
  telegram_sim: ["BOT·SIM", "bot"],
  webhook: ["HOOK", "bot"],
  notify: ["NOTIFY", "evt"],
  event: ["EVENT", "evt"],
  n8n: ["N8N", "n8n"],
  integration: ["SYNC", "n8n"],
  integration_trace: ["TRACE", "n8n"],
};

/** Куда вести из журнала: RAG, агент или n8n — по форме трассы. */
function target(r: any): string | null {
  if (r.type === "n8n") return "n8n";
  const steps = (r.trace || []).map((s: any) => s.step);
  if (!steps.length) return null;
  if (steps.includes("tool")) return "agent";
  if (steps[0] === "embedding") return "rag";
  if (steps.includes("llm")) return "agent";
  return null;
}

const titleOf = (r: any) =>
  r.type === "n8n"
    ? "Workflow n8n · " + (SOURCES[r.title]?.title || r.title)
    : String(r.type).startsWith("integration")
      ? "Запуск интеграции через очередь"
      : r.title;
const ABOUT: Record<string, [string, string]> = {
  event: [
    "Запись журнала бизнес-команд: кто и что изменил. Пишется в той же транзакции, что и само изменение.",
    "Event (аудит) + outbox в одной транзакции; видимость фильтруется по правам роли на объект.",
  ],
  webhook: [
    "Сообщение из Telegram, принятое вебхуком.",
    "Update сохранён после проверки secret_token; дедупликация по update_id.",
  ],
  n8n: [
    "Исполнение конвейера n8n со всеми шагами.",
    "source_sync + трасса из execution_data n8n (без строк с данными).",
  ],
  ai: [
    "Вопрос к AI: модель, стоимость и каждый шаг.",
    "job(kind=ai): trace, tokens, cost, provider; ретраи неоднозначных вызовов запрещены.",
  ],
};

export function LogView({
  data,
  go,
}: {
  data: Data;
  go: (section: string, opts: { job?: string; run?: string; prompt?: string }) => void;
}) {
  const eng = useEngineer();
  const [sel, setSel] = useState<string | null>(null);
  const log = useQuery({
    queryKey: ["under-log", data.session.role],
    queryFn: () => api("/under/log"),
    refetchInterval: 4000,
  });
  const rows: any[] = log.data?.rows || [];
  const row = rows.find((r) => r.id === sel) || null;
  const t = row && target(row);
  const max = Math.max(1, ...(row?.trace || []).map((s: any) => s.ms || 0));
  return (
    <div className="k-stage k-stage-log">
      <div className="k-log">
        <div className="k-log-head">
          <span className="k-live">
            <i />
            live · обновление каждые 4 с
          </span>
          <span>
            {rows.length} событий · {log.data?.scope || "текущая сессия"}
          </span>
        </div>
        {log.error && <div className="k-alert">{(log.error as any).message}</div>}
        {!rows.length && !log.isLoading && (
          <p className="k-hint k-log-empty">
            Пока тихо. Задайте вопрос в RAG или агенту, запустите workflow — события появятся здесь.
          </p>
        )}
        <div className="k-log-rows" role="list">
          {rows.map((r) => {
            const [tag, cls] = TYPE[r.type] || [String(r.type).toUpperCase(), "evt"];
            return (
              <button
                key={r.id}
                role="listitem"
                className={"k-log-row " + (sel === r.id ? "active" : "")}
                onClick={() => setSel(r.id)}
              >
                <time>{new Date(r.at).toLocaleTimeString("ru-RU", { timeZone: "Europe/Moscow" })}</time>
                <span className={"k-tag " + cls}>{tag}</span>
                <span className="k-log-title">{titleOf(r)}</span>
                <span className={"k-log-status " + r.status}>{r.status}</span>
                {eng && (
                  <span className="k-log-meta">
                    {[
                      r.model,
                      r.cost && "$" + Number(r.cost).toFixed(5),
                      r.trace?.length ? r.trace.length + " шаг." : "",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>
      <aside className="k-inspector">
        {!row ? (
          <>
            <span className="k-eyebrow">Журнал системы</span>
            <h3 className="k-h">Всё, что происходит — видно</h3>
            <p className="k-lead">
              <Say
                simple="Каждое сообщение боту, каждый вопрос к AI и каждая синхронизация оставляют след: когда, кто, сколько стоило и чем закончилось."
                eng="Объединённая лента: job (очередь, AI-трассы, стоимость), event (аудит бизнес-команд, вебхуки), source_sync (n8n). Фильтрация по правам роли на сервере."
              />
            </p>
            <p className="k-hint">Выберите событие слева — увидите его трассу и сможете проиграть на холсте.</p>
          </>
        ) : (
          <>
            <span className="k-eyebrow">
              {TYPE[row.type]?.[0] || row.type} ·{" "}
              {new Date(row.at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })}
            </span>
            <h3 className="k-h">{titleOf(row)}</h3>
            {ABOUT[row.type] && <p className="k-lead">{ABOUT[row.type][eng ? 1 : 0]}</p>}
            <Kv
              items={[
                ["Статус", row.status],
                ["Модель", row.model],
                ["Стоимость", row.cost ? "$" + Number(row.cost).toFixed(6) : ""],
                ["Исполнение n8n", row.execution_id ? "#" + row.execution_id : ""],
                ["Роль", row.role],
              ]}
            />
            {row.error && <div className="k-alert">{row.error}</div>}
            {row.trace?.length > 0 && (
              <Section title="Трасса">
                <div className="k-waterfall">
                  {row.trace.map((s: any, i: number) => (
                    <div
                      key={i}
                      className={
                        s.status === "error" || s.status === "denied" ? "err" : s.step === "fallback" ? "warn" : ""
                      }
                    >
                      <span>{s.title || s.node || s.step}</span>
                      <i style={{ width: Math.max(2, ((s.ms || 0) / max) * 100) + "%" }} />
                      <small>{ms(s.ms)}</small>
                    </div>
                  ))}
                </div>
              </Section>
            )}
            {t && (
              <button
                className="k-btn primary wide"
                onClick={() => go(t, t === "n8n" ? { run: row.id } : { job: row.id, prompt: row.title })}
              >
                Проиграть на холсте
                <ArrowRight size={15} />
              </button>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
