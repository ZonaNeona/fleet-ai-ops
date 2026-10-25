import { useMemo, useState } from "react";
import {
  Send,
  MonitorSmartphone,
  Server,
  ListOrdered,
  Cpu,
  Bot,
  Sparkles,
  BookOpen,
  ShieldCheck,
  Database,
  Workflow,
  Building2,
  ArrowRight,
  Play,
  MessageCircle,
  CalendarCheck,
  RefreshCw,
  FileSearch,
} from "lucide-react";
import { FlowCanvas, type FEdge, type FNode } from "./flow";
import { Frame, Say, Section, Timeline, useEngineer, useReplay } from "./kit";

type MapNode = Omit<FNode, "title" | "sub"> & {
  title: string;
  tech: string;
  simple: string;
  engineer: string;
};

const NODES: MapNode[] = [
  {
    id: "telegram",
    x: 0,
    y: 40,
    icon: Send,
    color: "#38bdf8",
    title: "Telegram-бот",
    tech: "Bot API · webhook",
    simple: "Водители и клиенты пишут в бот. Бот — не отдельная программа, а ещё один вход в ту же систему.",
    engineer:
      "Webhook /api/v1/telegram/webhook: проверка X-Telegram-Bot-Api-Secret-Token, дедупликация по update_id, Mini App — HMAC initData + auth_date.",
  },
  {
    id: "web",
    x: 0,
    y: 300,
    icon: MonitorSmartphone,
    color: "#a78bfa",
    title: "Кабинет",
    tech: "React 19 · PWA",
    simple: "Рабочее место сотрудников и личный кабинет водителя. Обновляется само, когда что-то происходит.",
    engineer:
      "React 19 + TanStack Query, cookie HttpOnly + проверка Origin, Server-Sent Events для живых обновлений, service worker.",
  },
  {
    id: "api",
    x: 250,
    y: 170,
    icon: Server,
    color: "#60a5fa",
    title: "API",
    tech: "FastAPI · OpenAPI",
    simple: "Единая дверь в систему: принимает запросы и сразу отвечает, а долгую работу передаёт дальше.",
    engineer:
      "FastAPI + Pydantic v2, OpenAPI /api/docs. Тяжёлые операции не выполняются в запросе — ставится Job, ответ 202.",
  },
  {
    id: "queue",
    x: 500,
    y: 170,
    icon: ListOrdered,
    color: "#fbbf24",
    title: "Очередь",
    tech: "PostgreSQL jobs",
    simple: "Задачи ждут своей очереди. Если сервер перезапустится — ничего не потеряется.",
    engineer:
      "Таблица job в PostgreSQL: SELECT … FOR UPDATE SKIP LOCKED, lease, повторы с backoff. Неоднозначные вызовы AI не повторяются, чтобы не списать бюджет дважды.",
  },
  {
    id: "worker",
    x: 750,
    y: 170,
    icon: Cpu,
    color: "#fb923c",
    title: "Воркер",
    tech: "Python · PM2",
    simple: "Исполнитель: берёт задачу, делает работу и отправляет результат.",
    engineer:
      "Отдельный процесс под PM2; эмбеддинги считаются в коротком дочернем процессе (fastembed, ~690 МБ на время расчёта) — память сервера не держится.",
  },
  {
    id: "agent",
    x: 1000,
    y: 40,
    icon: Bot,
    color: "#22d3ee",
    title: "AI-агент",
    tech: "tool calling",
    simple:
      "Помощник понимает вопрос и сам выбирает, какие данные ему нужны. Но видит только то, что разрешено вашей роли.",
    engineer:
      "OpenAI-совместимый tool calling, до 4 раундов; набор инструментов зависит от роли; аргументы — Pydantic-схемы; запись — только через черновик и подтверждение.",
  },
  {
    id: "llm",
    x: 1250,
    y: -70,
    icon: Sparkles,
    color: "#c084fc",
    title: "Языковые модели",
    tech: "qwen3.8 → deepseek",
    simple: "Сама «нейросеть». Если основная не отвечает — система переключается на запасную.",
    engineer:
      "Цепочка провайдеров: qwen/qwen3.8-flash (выбрана по eval на 60 кейсах) → deepseek-flash. Откат при 429/5xx/таймауте, дневной бюджет $0.50, учёт токенов и стоимости.",
  },
  {
    id: "rag",
    x: 1250,
    y: 140,
    icon: BookOpen,
    color: "#34d399",
    title: "База знаний",
    tech: "RAG · гибридный поиск",
    simple: "Регламенты и правила. Ответ строится только по найденным фрагментам — со ссылками.",
    engineer:
      "MiniLM-L12 (384d, локально) → pgvector HNSW cosine ∥ FTS russian (GIN) → RRF k=60 → порог 0.38 → LLM со structured output → проверка цитат.",
  },
  {
    id: "commands",
    x: 1000,
    y: 330,
    icon: ShieldCheck,
    color: "#f472b6",
    title: "Бизнес-команды",
    tech: "authz · idempotency",
    simple: "Любое изменение проходит проверку: кто вы, можно ли это делать сейчас, не повтор ли это.",
    engineer:
      "Объектная авторизация по роли, Idempotency-Key, оптимистичная версия, аудит + outbox в одной транзакции.",
  },
  {
    id: "postgres",
    x: 1250,
    y: 360,
    icon: Database,
    color: "#60a5fa",
    title: "PostgreSQL 16",
    tech: "NUMERIC · EXCLUDE · pgvector",
    simple: "Единый учёт: договоры, деньги, история. Две брони одной машины на одни даты физически невозможны.",
    engineer:
      "Деньги в NUMERIC, EXCLUDE USING gist для броней, pgvector + GIN в той же базе, ежедневный pg_dump, релизы со снимком.",
  },
  {
    id: "n8n",
    x: 750,
    y: 480,
    icon: Workflow,
    color: "#ff6d5a",
    title: "n8n",
    tech: "4 workflow",
    simple: "Конвейеры, которые забирают данные из внешних систем и приносят их на сверку.",
    engineer:
      "Webhook + расписание → HTTP к источнику → Code-нормализация и валидация схемы → подписанный HMAC-пакет → транзакционный ingest. Трасса исполнения читается из БД n8n.",
  },
  {
    id: "sources",
    x: 500,
    y: 480,
    icon: Building2,
    color: "#94a3b8",
    title: "Внешние системы",
    tech: "1С · Яндекс Про · ГИБДД",
    simple: "1С, Яндекс Про, штрафы, телематика. В демо — учебные копии с намеренными расхождениями.",
    engineer:
      "Моки в формате источников (OData 1С и т. п.), закрыты снаружи nginx; данные выводятся из пространства сессии.",
  },
];

const EDGES: FEdge[] = [
  { id: "telegram-api", from: "telegram", to: "api" },
  { id: "web-api", from: "web", to: "api" },
  { id: "api-queue", from: "api", to: "queue" },
  { id: "queue-worker", from: "queue", to: "worker" },
  { id: "worker-agent", from: "worker", to: "agent" },
  { id: "worker-commands", from: "worker", to: "commands" },
  { id: "agent-llm", from: "agent", to: "llm" },
  { id: "agent-rag", from: "agent", to: "rag" },
  { id: "agent-commands", from: "agent", to: "commands", out: "b", in: "t", label: "инструменты" },
  { id: "api-commands", from: "api", to: "commands", out: "b", in: "l" },
  { id: "commands-postgres", from: "commands", to: "postgres" },
  { id: "rag-postgres", from: "rag", to: "postgres", out: "b", in: "t", dashed: true, label: "pgvector" },
  { id: "commands-queue", from: "commands", to: "queue", out: "t", in: "b", dashed: true, label: "outbox" },
  { id: "sources-n8n", from: "sources", to: "n8n" },
  { id: "n8n-commands", from: "n8n", to: "commands", out: "r", in: "b", label: "ingest · HMAC" },
];

type Scenario = {
  id: string;
  icon: any;
  title: string;
  try?: { section: string; prompt?: string; label: string };
  steps: (Omit<Frame, "key" | "label"> & { label: string; simple: string; eng: string })[];
};

const back = (...ids: string[]) => ids.map((id) => ({ id, reverse: true }));

const SCENARIOS: Scenario[] = [
  {
    id: "debt",
    icon: MessageCircle,
    title: "Водитель спрашивает долг в боте",
    try: { section: "agent", prompt: "Сколько я должен?", label: "Задать этот вопрос агенту" },
    steps: [
      {
        node: "telegram",
        label: "Сообщение",
        simple: "Водитель пишет в бот: «Сколько я должен?»",
        eng: "Telegram доставляет Update на вебхук; заголовок secret_token сверяется в постоянное время.",
      },
      {
        node: "api",
        edges: ["telegram-api"],
        label: "Приём",
        simple: "Сервер принимает сообщение и сразу отвечает Telegram «принято».",
        eng: "update_id уникален — повторная доставка не создаст второй задачи. Ответ 200 за миллисекунды.",
      },
      {
        node: "queue",
        edges: ["api-queue"],
        label: "Очередь",
        simple: "Вопрос становится задачей в очереди.",
        eng: "INSERT job(kind=telegram, role=driver). Роль закреплена в задаче, а не берётся из текста.",
      },
      {
        node: "worker",
        edges: ["queue-worker"],
        label: "Воркер",
        simple: "Свободный исполнитель берёт задачу.",
        eng: "SELECT … FOR UPDATE SKIP LOCKED — два воркера не возьмут одну задачу.",
      },
      {
        node: "agent",
        edges: ["worker-agent"],
        label: "Агент",
        simple: "Помощнику выдают только инструменты, разрешённые водителю.",
        eng: "tools_for(driver): list_vehicles, find_contract, search_knowledge, get_balance, vehicle_economics, create_ticket.",
      },
      {
        node: "llm",
        edges: ["agent-llm"],
        label: "Модель",
        simple: "Модель решает: чтобы ответить, нужен баланс.",
        eng: "qwen3.8-flash → tool_call get_balance({}). Если модель недоступна — откат на deepseek-flash.",
      },
      {
        node: "commands",
        edges: [...back("agent-llm"), "agent-commands"],
        label: "Права",
        simple: "Система проверяет: водитель видит только свой долг.",
        eng: "get_balance → reports.report(sp) в scope роли и объекта; чужие договоры не попадут в выборку.",
      },
      {
        node: "postgres",
        edges: ["commands-postgres"],
        label: "Учёт",
        simple: "Цифры берутся из учёта, а не придумываются.",
        eng: "Начисления − платежи в NUMERIC, просрочка по корзинам (aging).",
      },
      {
        node: "agent",
        edges: back("commands-postgres", "agent-commands"),
        label: "Ответ",
        simple: "Модель получает цифры и пишет ответ человеческим языком.",
        eng: "Второй раунд: результат инструмента → модель; стоимость и токены пишутся в Usage.",
      },
      {
        node: "telegram",
        edges: back("worker-agent", "queue-worker", "api-queue", "telegram-api"),
        label: "В чат",
        simple: "Ответ приходит в чат через несколько секунд.",
        eng: "sendMessage; ответ и трасса доступны в журнале «Под капотом».",
      },
    ],
  },
  {
    id: "rules",
    icon: FileSearch,
    title: "Вопрос по регламенту",
    try: { section: "rag", prompt: "Какие документы нужны водителю?", label: "Открыть конвейер RAG" },
    steps: [
      {
        node: "web",
        label: "Вопрос",
        simple: "Сотрудник спрашивает: «Какие документы нужны водителю?»",
        eng: "POST /api/v1/under/rag → 202, job id.",
      },
      {
        node: "api",
        edges: ["web-api"],
        label: "API",
        simple: "Вопрос принят.",
        eng: "Pydantic-валидация, лимит 2000 символов, бюджет сессии.",
      },
      {
        node: "queue",
        edges: ["api-queue"],
        label: "Очередь",
        simple: "Задача поставлена в очередь.",
        eng: "job(kind=ai, mode=rag).",
      },
      {
        node: "worker",
        edges: ["queue-worker"],
        label: "Воркер",
        simple: "Исполнитель начинает поиск.",
        eng: "Эмбеддинг считается локально — текст не уходит внешним сервисам.",
      },
      {
        node: "rag",
        edges: ["worker-agent", "agent-rag"],
        label: "Поиск",
        simple: "Поиск находит фрагменты по смыслу и по словам.",
        eng: "«документы» ≈ «паспорт, ВУ, СНИЛС» — вектор находит то, что FTS пропустит.",
      },
      {
        node: "postgres",
        edges: ["rag-postgres"],
        label: "pgvector",
        simple: "Фрагменты хранятся в той же базе, что и учёт.",
        eng: "HNSW (cosine) + GIN tsvector, слияние RRF, отсечение ниже порога 0.38.",
      },
      {
        node: "llm",
        edges: [...back("rag-postgres", "agent-rag"), "agent-llm"],
        label: "Модель",
        simple: "Модель отвечает только по найденному и ставит ссылки.",
        eng: "Structured output {answer, citations}; цитата вне найденных → ответ отклоняется.",
      },
      {
        node: "web",
        edges: back("agent-llm", "worker-agent", "queue-worker", "api-queue", "web-api"),
        label: "Ответ",
        simple: "Ответ со ссылками на источники. Нет в базе — честно говорит «не нашёл».",
        eng: "Нет фрагментов выше порога → модель не вызывается вовсе (guard).",
      },
    ],
  },
  {
    id: "booking",
    icon: CalendarCheck,
    title: "Клиент бронирует автомобиль",
    steps: [
      {
        node: "web",
        label: "Бронь",
        simple: "Клиент выбирает машину и даты в кабинете.",
        eng: "POST /api/v1/commands {action: contract.create} + Idempotency-Key.",
      },
      {
        node: "api",
        edges: ["web-api"],
        label: "API",
        simple: "Запрос принят.",
        eng: "Проверка cookie-сессии и Origin.",
      },
      {
        node: "commands",
        edges: ["api-commands"],
        label: "Проверки",
        simple: "Проверка прав и правил: можно ли этому клиенту эту машину на эти даты.",
        eng: "Повторный запрос с тем же ключом вернёт тот же результат — двойного клика не будет.",
      },
      {
        node: "postgres",
        edges: ["commands-postgres"],
        label: "Транзакция",
        simple: "Две брони одной машины на одни даты база просто не даст сохранить.",
        eng: "EXCLUDE USING gist (vehicle WITH =, period WITH &&); договор, аудит и outbox — в одной транзакции.",
      },
      {
        node: "queue",
        edges: [...back("commands-postgres"), "commands-queue"],
        label: "Outbox",
        simple: "Уведомление ставится в очередь вместе с бронью — не раньше и не позже.",
        eng: "Outbox-паттерн: событие не потеряется и не уйдёт, если транзакция откатилась.",
      },
      {
        node: "worker",
        edges: ["queue-worker"],
        label: "Уведомить",
        simple: "Менеджер получает сообщение в Telegram, кабинеты обновляются сами.",
        eng: "notify → Telegram sendMessage; SSE /api/v1/events → TanStack Query invalidate.",
      },
      {
        node: "web",
        edges: back("api-queue", "web-api"),
        label: "Обновлено",
        simple: "Бронь видна у всех, кому положено.",
        eng: "Событие фильтруется по правам получателя.",
      },
    ],
  },
  {
    id: "sync",
    icon: RefreshCw,
    title: "Синхронизация с 1С",
    try: { section: "n8n", label: "Открыть workflow n8n" },
    steps: [
      {
        node: "n8n",
        label: "Запуск",
        simple: "По расписанию или по кнопке запускается конвейер n8n.",
        eng: "Schedule (каждый час) или Webhook из кабинета с подписанным контекстом запуска.",
      },
      {
        node: "sources",
        edges: [{ id: "sources-n8n", reverse: true }],
        label: "1С",
        simple: "n8n забирает данные из 1С: пробег и начисления.",
        eng: "HTTP → OData Catalog_ТС / AccumulationRegister (учебный мок).",
      },
      {
        node: "n8n",
        edges: ["sources-n8n"],
        label: "Нормализация",
        simple: "Данные приводятся к общему виду и проверяются.",
        eng: "Code-нода: схема, числа ≥ 0, обязательный код ТС. Ошибка → ветка «Ошибка источника».",
      },
      {
        node: "commands",
        edges: ["n8n-commands"],
        label: "Ingest",
        simple: "Пакет принимается, только если подпись верна.",
        eng: "HMAC run+space, защита от повтора; повторный запуск не создаёт дубликатов.",
      },
      {
        node: "postgres",
        edges: ["commands-postgres"],
        label: "Сверка",
        simple: "Система сравнивает с учётом и показывает расхождения.",
        eng: "source_sync + Item(kind=discrepancy) → виджет «Сверка» на дашборде.",
      },
      {
        node: "web",
        edges: back("commands-postgres", "api-commands", "web-api"),
        label: "Дашборд",
        simple: "Собственник видит: «у 3 машин пробег в 1С не совпадает».",
        eng: "Клик по расхождению открывает карточку автомобиля.",
      },
    ],
  },
];

export function SystemMap({ go }: { go: (section: string, prompt?: string) => void }) {
  const eng = useEngineer();
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [run, setRun] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const frames: Frame[] = useMemo(
    () =>
      (scenario?.steps || []).map((s, i) => ({
        ...s,
        key: scenario!.id + i,
        hold: 1500,
      })),
    [scenario],
  );
  const replay = useReplay(frames, scenario ? scenario.id + run : "none");
  const step = replay.current ? scenario?.steps[replay.pos] : null;
  const node = NODES.find((n) => n.id === (selected || (step ? step.node : "")));
  const nodes: FNode[] = NODES.map((n) => ({
    ...n,
    title: n.title,
    sub: eng ? n.tech : undefined,
    size: n.id === "agent" || n.id === "api" ? "lg" : "md",
    state: scenario ? replay.states[n.id] : undefined,
    dim: !!scenario && !frames.some((f) => f.node === n.id),
  }));
  const start = (s: Scenario) => {
    setSelected(null);
    setScenario(s);
    setRun((r) => r + 1);
  };
  return (
    <div className="k-stage">
      <div className="k-canvas-wrap">
        <div className="k-canvas-head">
          <div className="k-scenarios">
            {SCENARIOS.map((s) => (
              <button key={s.id} className={scenario?.id === s.id ? "active" : ""} onClick={() => start(s)}>
                <s.icon size={15} />
                {s.title}
              </button>
            ))}
          </div>
        </div>
        <FlowCanvas
          nodes={nodes}
          edges={replay.paint(EDGES)}
          focus={replay.playing ? replay.current?.node : null}
          selected={selected || (replay.playing ? null : null)}
          onSelect={setSelected}
          scene={scenario?.id + "-" + replay.done}
        />
        {step && (
          <div className="k-caption" key={replay.pos}>
            <span>
              {replay.pos + 1}/{frames.length}
            </span>
            <p>{eng ? step.eng : step.simple}</p>
          </div>
        )}
      </div>
      <aside className="k-inspector">
        {node ? (
          <>
            <div className="k-ins-head">
              <span className="k-ins-icon" style={{ ["--c" as any]: node.color }}>
                <node.icon size={20} />
              </span>
              <div>
                <span className="k-eyebrow">{eng ? node.tech : "Компонент системы"}</span>
                <h3>{node.title}</h3>
              </div>
            </div>
            <p className="k-lead">{eng ? node.engineer : node.simple}</p>
            {!eng && <p className="k-hint">Переключите «Инженер» вверху — увидите, как это устроено технически.</p>}
          </>
        ) : (
          <>
            <span className="k-eyebrow">Карта системы</span>
            <h3 className="k-h">Одна система — много входов</h3>
            <p className="k-lead">
              <Say
                simple="Бот, кабинет и интеграции — это не три разные программы, а три входа в одну систему с общими правилами и единым учётом."
                eng="Монолит FastAPI + PostgreSQL как единый источник правды; асинхронная работа — через очередь в той же БД; AI и интеграции — изолированные исполнители с ролевыми ограничениями."
              />
            </p>
            <p className="k-hint">
              Выберите сценарий — и посмотрите, как запрос проходит через систему. Нажмите на любой узел, чтобы узнать,
              что он делает.
            </p>
          </>
        )}
        {scenario && (
          <Section title={scenario.title}>
            <ol className="k-steps">
              {scenario.steps.map((s, i) => (
                <li
                  key={i}
                  className={i === replay.pos ? "now" : i < replay.pos || replay.done ? "done" : ""}
                  onClick={() => replay.seek(i)}
                >
                  <b>{s.label}</b>
                  <span>{eng ? s.eng : s.simple}</span>
                </li>
              ))}
            </ol>
            {scenario.try && (
              <button className="k-btn primary wide" onClick={() => go(scenario.try!.section, scenario.try!.prompt)}>
                {scenario.try.label}
                <ArrowRight size={15} />
              </button>
            )}
          </Section>
        )}
        {!scenario && (
          <Section title="Сценарии">
            <div className="k-scenario-list">
              {SCENARIOS.map((s) => (
                <button key={s.id} onClick={() => start(s)}>
                  <s.icon size={16} />
                  <span>{s.title}</span>
                  <Play size={13} />
                </button>
              ))}
            </div>
          </Section>
        )}
      </aside>
      <Timeline frames={frames} replay={replay} empty="Выберите сценарий над схемой — шаги появятся здесь" />
    </div>
  );
}
