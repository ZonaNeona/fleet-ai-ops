import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, LoaderCircle, MessageSquareText, Play, ScrollText } from "lucide-react";
import { api, rub } from "./lib";

type Deal = {
  id: string;
  title: string;
  funnel: number;
  stage: string;
  contract: string | null;
  amount: string;
  stuck: boolean;
};
type Journal = {
  comments: { ID: string; COMMENT: string; CREATED: string }[];
  tasks: { id: string; TITLE: string; DESCRIPTION?: string }[];
  events: { event_token: string; return_values: Record<string, string>; log_message: string; at: string }[];
  log: { method: string; at: string; source: string; params: string }[];
  deal: Record<string, string> | null;
};
const when = (v: string) =>
  new Date(v).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/**
 * How the PHP + Vue application looks inside Bitrix24: a deal card with the app's tab and the robot.
 * The tab is the real app (b24app/) in an iframe; the robot button sends the app what a portal sends.
 */
export function B24AppTab({
  deals,
  stages,
  toast,
}: {
  deals: Deal[];
  stages: Record<string, string>;
  toast: (m: string) => void;
}) {
  const q = useQueryClient();
  const choices = useMemo(() => deals.filter((d) => d.contract || d.funnel === 1).slice(0, 30), [deals]);
  const [deal, setDeal] = useState(choices[0]?.id || "");
  const [robot, setRobot] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [frame, setFrame] = useState(0);
  const session = useQuery({
    queryKey: ["b24app-session"],
    queryFn: () =>
      api<{ key: string; widget: string; rest: string; robot: string }>("/b24app/session", {
        method: "POST",
        body: "{}",
      }),
    staleTime: 60 * 60 * 1000,
  });
  const journal = useQuery({
    queryKey: ["b24app-journal", deal],
    queryFn: () => api<Journal>(`/b24app/journal?deal=${deal}`),
    enabled: !!deal,
  });
  useEffect(() => setRobot(null), [deal]);

  const run = async () => {
    setBusy(true);
    try {
      setRobot(await api("/b24app/robot", { method: "POST", body: JSON.stringify({ deal }) }));
      await q.invalidateQueries({ queryKey: ["b24app-journal", deal] });
      setFrame((n) => n + 1);
    } catch (e: any) {
      toast(e.message);
    } finally {
      setBusy(false);
    }
  };

  const d = journal.data?.deal;
  return (
    <div className="ba">
      <p className="cr-lead">
        Локальное приложение Битрикс24: <b>PHP 8</b> (установка, обработчик робота и событий) и <b>Vue 3</b> (вкладка
        «Водитель» в карточке сделки). Ниже — оно же, открытое на эмуляторе портала: приложение говорит с ним по REST
        так же, как с настоящим Битрикс24.
      </p>
      <div className="ba-pick">
        <select value={deal} onChange={(e) => setDeal(e.target.value)} aria-label="Сделка">
          {choices.map((x) => (
            <option key={x.id} value={x.id}>
              #{x.id} · {x.title}
            </option>
          ))}
        </select>
        <button className="button primary" disabled={busy || !deal} onClick={run}>
          {busy ? <LoaderCircle size={16} className="spin" /> : <Play size={16} />} Запустить робота «Проверить
          водителя»
        </button>
      </div>

      <div className="ba-grid">
        <section className="ba-card">
          <header>
            <small>CRM · Сделка #{deal}</small>
            <h3>{d?.TITLE || "…"}</h3>
            <div className="ba-meta">
              <span className="ba-stage">{stages[d?.STAGE_ID || ""] || d?.STAGE_ID}</span>
              {d?.OPPORTUNITY && Number(d.OPPORTUNITY) > 0 && <b>{rub(d.OPPORTUNITY)}</b>}
              {d?.UF_CRM_CONTRACT && <span>договор {d.UF_CRM_CONTRACT}</span>}
            </div>
          </header>
          <div className="ba-tabs">
            <span>Общие</span>
            <span className="active">Водитель · приложение</span>
            <span>История</span>
          </div>
          {session.data && deal ? (
            <iframe
              key={deal + ":" + frame}
              title="Приложение Битрикс24 «Водитель»"
              src={`${session.data.widget}?demo=1&deal=${deal}&key=${encodeURIComponent(session.data.key)}`}
            />
          ) : (
            <div className="ba-wait">
              <LoaderCircle className="spin" /> Готовим приложение…
            </div>
          )}
        </section>

        <aside className="ba-side">
          <section>
            <h4>
              <Bot size={15} /> Робот
            </h4>
            {robot ? (
              <div className={"ba-robot " + (robot.app?.ok ? "ok" : "bad")}>
                <b>{robot.app?.ok ? "Можно выдавать" : "Есть замечания"}</b>
                <ul>
                  {(robot.app?.reasons || []).map((r: string) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
                {robot.app?.task && <small>Задача №{robot.app.task} поставлена менеджеру</small>}
              </div>
            ) : (
              <p className="muted">
                Бизнес-процесс сделки доходит до робота → портал вызывает <code>robot.php</code> приложения → приложение
                спрашивает учёт таксопарка и пишет в сделку комментарий, задачу и ответ робота{" "}
                <code>bizproc.event.send</code>.
              </p>
            )}
          </section>
          <section>
            <h4>
              <MessageSquareText size={15} /> Лента сделки
            </h4>
            {(journal.data?.comments || [])
              .slice()
              .reverse()
              .map((c) => (
                <div className="ba-comment" key={c.ID}>
                  <small>{when(c.CREATED)}</small>
                  {c.COMMENT}
                </div>
              ))}
            {(journal.data?.tasks || []).map((t) => (
              <div className="ba-comment task" key={t.id}>
                <small>Задача №{t.id}</small>
                {t.TITLE}
              </div>
            ))}
            {!journal.data?.comments.length && !journal.data?.tasks.length && <p className="muted">Пока пусто.</p>}
          </section>
          <section>
            <h4>
              <ScrollText size={15} /> Запись в портал (REST)
            </h4>
            <div className="ba-log">
              {(journal.data?.log || [])
                .slice()
                .reverse()
                .map((l, i) => (
                  <div key={i}>
                    <code>{l.method}</code>
                    <small>
                      {when(l.at)} · {l.source}
                    </small>
                  </div>
                ))}
              {!journal.data?.log.length && <p className="muted">Приложение ещё ничего не писало.</p>}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
