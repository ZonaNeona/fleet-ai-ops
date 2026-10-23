import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CalendarRange,
  CircleCheck,
  CircleDashed,
  ExternalLink,
  MessagesSquare,
  PenTool,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { api } from "./lib";
import "./work.css";

const GH = "https://github.com/ZonaNeona/fleet-ai-ops";
const PATH = [
  { icon: MessagesSquare, title: "Созвон", text: "Разбираем процесс: где теряются деньги и время, какие системы уже есть — Битрикс24, 1С, таблицы, Telegram.", result: "Список болей с цифрами" },
  { icon: PenTool, title: "Схема", text: "Рисуем процесс «как есть» и «как будет» и отмечаем, где работает автоматизация, а где решает человек.", result: "Схема процесса в Miro" },
  { icon: CalendarRange, title: "Смета", text: "Дорожная карта: этапы и задачи с оценкой и результатом простыми словами. Цена фиксируется до старта.", result: "Дорожная карта и цена" },
  { icon: ShieldCheck, title: "Исполнение", text: "После каждого этапа — выкладка на ваш стенд и приёмка. Код в вашем репозитории, проверки в CI.", result: "Работающая система по этапам" },
  { icon: Wrench, title: "Сопровождение", text: "Абонентское обслуживание: пакет часов в месяц на доработки и поддержку.", result: "Система растёт вместе с бизнесом" },
];
const AI_DEV = [
  ["Агенты — основной инструмент", "Claude Code, Cursor, Codex: правила проекта в CLAUDE.md, субагенты для поиска и ревью, MCP, параллельная работа в ветках."],
  ["План до кода", "Каждый этап начинается с плана: что просят заказчики, что переиспользуем, как проверить. План утверждает заказчик."],
  ["Проверки, а не доверие", "Тесты на настоящем PostgreSQL, линтеры и типы в CI, проверка в браузере на десктопе и телефоне после каждой выкладки."],
  ["Ответственность — на мне", "Код агентов читаю и проверяю сам, отвечаю за него как за свой. Секреты и чужие данные в репозиторий не попадают — это тоже проверка в CI."],
];
const RULES = [
  ["Сначала только чтение", "К вашим системам подключаемся на чтение. Запись — только там, где вы её разрешили."],
  ["ИИ не действует сам", "Всё, что меняет деньги и данные, — черновик или решение человека."],
  ["Расходы под контролем", "У моделей суточный потолок, стоимость каждого вызова видна в трассе."],
  ["Проверяемо", "У каждой задачи есть ссылка, где результат можно проверить самому."],
];
type Task = { title: string; outcome: string; status: "done" | "next"; check?: [string, string] };
const STAGES: { code: string; title: string; date: string; tasks: Task[] }[] = [
  {
    code: "Э-0", title: "Фундамент и чистый репозиторий", date: "23.10.2026",
    tasks: [
      { title: "Нейтральные имена, чистка, новый публичный репозиторий", outcome: "Код открыт и не содержит чужих данных.", status: "done", check: ["GitHub", GH] },
      { title: "CI: тесты на PostgreSQL + pgvector, сборка, gitleaks, приватные имена", outcome: "Каждое изменение проверяется автоматически.", status: "done", check: ["CI", GH + "/actions"] },
      { title: "Выкладка одной командой с бэкапом и откатом", outcome: "Релиз занимает минуту и не ломает открытые вкладки.", status: "done", check: ["deploy.sh", GH + "/blob/main/scripts/deploy.sh"] },
    ],
  },
  {
    code: "Э-1", title: "Входящие документы на графе", date: "23.10.2026",
    tasks: [
      { title: "Граф LangGraph: распознавание → сверка → решение человека → проводка", outcome: "Штрафы, счета СТО и права кандидатов проводятся сами, если всё сошлось.", status: "done", check: ["Документы", "#app/inbox"] },
      { title: "Сканы читает vision-модель, PDF с текстом — правила", outcome: "Фото из бота превращается в проводку.", status: "done", check: ["Граф под капотом", "#under/docs"] },
    ],
  },
  {
    code: "Э-2", title: "CRM: Битрикс24", date: "23.10.2026",
    tasks: [
      { title: "Воронки найма водителей и проката, лиды, журнал REST", outcome: "Видно, где зависли кандидаты и заявки.", status: "done", check: ["CRM", "#app/crm"] },
      { title: "Сверка «оплачено в CRM ↔ деньги в учёте»", outcome: "Расхождения видны с суммой и договором.", status: "done", check: ["Сверка", "#app/crm"] },
    ],
  },
  {
    code: "Э-3", title: "Голос и звонки", date: "23.10.2026",
    tasks: [
      { title: "Голосовые в боте и микрофон эмулятора → распознавание речи", outcome: "Водитель может просто сказать, что случилось.", status: "done", check: ["Бот", "#app/bot"] },
      { title: "Разбор звонков диспетчерской по чек-листу", outcome: "Балл и конкретный совет по каждому звонку.", status: "done", check: ["Звонки", "#app/calls"] },
    ],
  },
  {
    code: "Э-4", title: "MCP и измеренное качество", date: "23.10.2026",
    tasks: [
      { title: "MCP-сервер над инструментами агента", outcome: "Claude Desktop или Cursor работают с таксопарком через те же инструменты.", status: "done", check: ["MCP", "#under/mcp"] },
      { title: "Качество поиска по эталонным вопросам в CI и при выкладке", outcome: "Точность поиска измерена, а не обещана.", status: "done", check: ["Качество", "#app/work"] },
    ],
  },
  {
    code: "Э-5", title: "Как мы работаем и сводка", date: "23.10.2026",
    tasks: [
      { title: "Утренняя сводка собственнику в Telegram", outcome: "Деньги вчера, долг, машины в минусе, что ждёт человека.", status: "done" },
      { title: "Этот раздел: путь заказчика, дорожная карта, качество", outcome: "Процесс работы виден на примере самого стенда.", status: "done" },
    ],
  },
  {
    code: "Э-6", title: "Запуск одной командой и видимое качество кода", date: "23.10.2026",
    tasks: [
      { title: "docker compose up: PostgreSQL + pgvector, Redis, API, воркер, веб", outcome: "Стенд поднимается на любой машине без ключей, интеграции — в режиме эмуляторов.", status: "done", check: ["docker-compose.yml", GH + "/blob/main/docker-compose.yml"] },
      { title: "CI: ruff, mypy, тесты с покрытием, сборка образов и запуск compose", outcome: "Каждое изменение проверяется так же, как на сервере.", status: "done", check: ["CI", GH + "/actions"] },
      { title: "Замер тестов и покрытия при каждой выкладке", outcome: "Цифры на этом экране сняты с той версии, что сейчас работает.", status: "done" },
    ],
  },
  {
    code: "Э-7", title: "Битрикс24 по-настоящему: приложение на PHP + Vue", date: "23.10.2026",
    tasks: [
      { title: "Приложение: вкладка «Водитель» в сделке (Vue 3) и робот «Проверить водителя» (PHP 8)", outcome: "Менеджер видит долг, штрафы и расхождения прямо в карточке сделки; робот пишет вердикт в сделку и ставит задачу.", status: "done", check: ["Приложение Б24", "#app/crm"] },
      { title: "Эмулятор портала по HTTP с записью: сделки, лента, задачи, дела, смарт-процесс «Автомобиль»", outcome: "Приложение работает с эмулятором тем же кодом, что с настоящим порталом.", status: "done", check: ["ADR 0010", GH + "/blob/main/docs/adr/0010-b24-app-php-vue.md"] },
      { title: "Телефония: вебхук виртуальной АТС → дело-звонок в Битрикс24 → разбор записи", outcome: "Звонок в диспетчерскую сам оказывается в CRM и получает оценку по чек-листу.", status: "done", check: ["Звонки", "#app/calls"] },
    ],
  },
  {
    code: "Э-8", title: "Обмен с 1С в обе стороны", date: "23.10.2026",
    tasks: [
      { title: "Выгрузка начислений и оплат в 1С документами по стандартному OData", outcome: "Бухгалтер видит акты и поступления в 1С без двойного ввода; повторный обмен не создаёт дублей.", status: "done", check: ["1С · обмен", "#app/onec"] },
      { title: "Сверка «учёт ↔ 1С» в обе стороны", outcome: "Находит то, что бухгалтер внёс руками: выписку только в 1С и акт с опечаткой в сумме.", status: "done", check: ["ADR 0011", GH + "/blob/main/docs/adr/0011-onec-odata-exchange.md"] },
      { title: "Перевести workflow 1С в n8n на этот клиент", outcome: "n8n ходит в ту же базу 1С по OData, а не в снимок.", status: "next" },
    ],
  },
];

export function WorkPage() {
  const [tab, setTab] = useState("path");
  const quality = useQuery({ queryKey: ["quality"], queryFn: () => api<any>("/quality"), enabled: tab === "quality" });
  const digest = useQuery({ queryKey: ["digest"], queryFn: () => api<any>("/digest"), enabled: tab === "quality" });
  const r = quality.data?.retrieval;
  const code = quality.data?.code;
  const pct = (v: number) => Math.round(v * 100) + "%";

  return (
    <div className="wk">
      <div className="list-toolbar">
        <div className="tabs">
          {[["path", "Путь заказчика"], ["roadmap", "Дорожная карта стенда"], ["quality", "Код и качество"]].map(([id, label]) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>
          ))}
        </div>
      </div>

      {tab === "path" && (
        <>
          <ol className="wk-path">
            {PATH.map((p, i) => (
              <li key={p.title}>
                <div className="wk-path-top"><span><p.icon size={16} /></span><small>0{i + 1}</small></div>
                <b>{p.title}</b>
                <p>{p.text}</p>
                <small className="wk-result">Результат: <b>{p.result}</b></small>
              </li>
            ))}
          </ol>
          <div className="wk-rules">
            {RULES.map(([t, d]) => (
              <div key={t}><b>{t}</b><span>{d}</span></div>
            ))}
          </div>
          <h3 className="wk-h">Разработка с ИИ-агентами</h3>
          <div className="wk-rules">
            {AI_DEV.map(([t, d]) => (
              <div key={t}><b>{t}</b><span>{d}</span></div>
            ))}
          </div>
        </>
      )}

      {tab === "roadmap" && (
        <div className="wk-stages">
          {STAGES.map((st) => (
            <section key={st.code}>
              <header><small>{st.code} · {st.date}</small><h3>{st.title}</h3></header>
              {st.tasks.map((t) => (
                <div className={"wk-task " + t.status} key={t.title}>
                  {t.status === "done" ? <CircleCheck size={16} /> : <CircleDashed size={16} />}
                  <div>
                    <b>{t.title}</b>
                    <span>{t.outcome}</span>
                  </div>
                  {t.check && (
                    <a href={t.check[1]} target={t.check[1].startsWith("#") ? undefined : "_blank"} rel="noopener"
                       onClick={(e) => { if (t.check![1].startsWith("#")) { e.preventDefault(); location.hash = t.check![1]; location.reload(); } }}>
                      {t.check[0]} <ExternalLink size={12} />
                    </a>
                  )}
                </div>
              ))}
            </section>
          ))}
          <p className="muted">Статус «готово» значит: код в репозитории и проходит CI. Каждый этап выкладывается на стенд и принимается отдельно.</p>
        </div>
      )}

      {tab === "quality" && (
        <div className="wk-quality">
          {code && (
            <section>
              <h3>Код · замер при выкладке</h3>
              <div className="wk-kpis">
                <div><b>{code.python.passed}/{code.python.tests}</b><span>тестов прошло (PostgreSQL + pgvector)</span></div>
                <div><b>{code.python.coverage}%</b><span>покрытие кода тестами</span></div>
                <div><b>{code.python.ruff && code.python.mypy ? "чисто" : "есть замечания"}</b><span>ruff · mypy</span></div>
                <div><b>{(code.python.lines + code.web.lines).toLocaleString("ru-RU")}</b><span>строк: Python {code.python.files} файлов, TS {code.web.files}</span></div>
              </div>
              <p className="muted">{code.checks}. Замер: {new Date(code.at).toLocaleString("ru-RU")}.</p>
            </section>
          )}
          <section>
            <h3>Поиск по регламентам</h3>
            {r ? (
              <>
                <div className="wk-kpis">
                  <div><b>{pct(r.hit_at_1)}</b><span>нужный регламент первым</span></div>
                  <div><b>{pct(r.hit_at_3)}</b><span>в первой тройке</span></div>
                  <div><b>{pct(r.refusals)}</b><span>честных отказов вне базы</span></div>
                  <div><b>{r.ms_avg} мс</b><span>в среднем на вопрос</span></div>
                </div>
                <p className="muted">{quality.data.method} Замер: {new Date(quality.data.at).toLocaleString("ru-RU")}, {quality.data.cases} вопросов.</p>
                <details>
                  <summary>Все вопросы</summary>
                  <table>
                    <tbody>
                      {quality.data.rows.map((x: any) => (
                        <tr key={x.question} className={x.hit3 ? "" : "bad"}>
                          <td>{x.hit3 ? "✓" : "✗"}</td><td>{x.question}</td><td>{Array.isArray(x.expected) ? x.expected.join(" / ") : "отказ"}</td><td>{x.found.join(", ") || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              </>
            ) : (
              <p className="muted">Отчёт появится после первой выкладки: он считается на сервере при каждом релизе.</p>
            )}
          </section>
          <section>
            <h3>Код</h3>
            <ul className="wk-links">
              <li><a href={GH} target="_blank" rel="noopener">Репозиторий на GitHub <ExternalLink size={12} /></a></li>
              <li><a href={GH + "/actions"} target="_blank" rel="noopener">CI: тесты на PostgreSQL + pgvector, сборка, gitleaks <ExternalLink size={12} /></a></li>
              <li><a href={GH + "/tree/main/docs/adr"} target="_blank" rel="noopener">Архитектурные решения (ADR) <ExternalLink size={12} /></a></li>
              <li><a href={GH + "/blob/main/docs/DEMO.md"} target="_blank" rel="noopener">Сценарий показа <ExternalLink size={12} /></a></li>
            </ul>
          </section>
          {digest.data?.text && (
            <section>
              <h3>Утренняя сводка собственнику · {digest.data.schedule}</h3>
              <pre className="wk-digest" dangerouslySetInnerHTML={{ __html: digest.data.text.replace(/<(?!\/?b>)/g, "&lt;") }} />
            </section>
          )}
        </div>
      )}
    </div>
  );
}
