import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Send,
  Webhook,
  ListOrdered,
  GitBranch,
  UserRound,
  LayoutGrid,
  MessageSquareText,
  ShieldCheck,
  Database,
  Bot,
  BookOpen,
  ClipboardCheck,
  BellRing,
  Reply,
  Play,
  ArrowRight,
  Wallet,
  Wrench,
  UserPlus,
} from "lucide-react";
import { api, Data } from "../lib";
import { FlowCanvas, type FEdge, type FNode } from "./flow";
import { Frame, Say, Section, Timeline, useEngineer, useReplay } from "./kit";

type N = Omit<FNode, "sub"> & { tech: string; simple: string; engineer: string };

const NODES: N[] = [
  { id: "tg", x: 0, y: 170, icon: Send, color: "#2aabee", title: "Telegram", tech: "Bot API · Mini App", simple: "Водитель, клиент или сотрудник пишет боту или нажимает кнопку.", engineer: "Update (message / callback_query) приходит POST-ом на вебхук; Mini App авторизуется по HMAC initData." },
  { id: "hook", x: 220, y: 170, icon: Webhook, color: "#a78bfa", title: "Вебхук", tech: "secret_token · дедуп", simple: "Сервер проверяет, что сообщение действительно от Telegram, и сразу отвечает «принято».", engineer: "X-Telegram-Bot-Api-Secret-Token сравнивается в постоянное время; update_id пишется в System — повторная доставка не создаст второго задания." },
  { id: "queue", x: 440, y: 170, icon: ListOrdered, color: "#fbbf24", title: "Очередь", tech: "job kind=telegram", simple: "Сообщение ждёт исполнителя — ничего не потеряется при перезапуске.", engineer: "Job в PostgreSQL, воркер берёт SKIP LOCKED; эмулятор ставит job kind=telegram_sim и вызывает тот же handle()." },
  { id: "router", x: 660, y: 170, icon: GitBranch, color: "#22d3ee", title: "Маршрутизатор", tech: "telegram.handle()", simple: "Бот понимает, кто пишет и что это: команда, кнопка меню или свободный текст.", engineer: "Пространство по tg_user (FOR UPDATE), роль из пространства, а не из текста; callback-префиксы d: c: m: s: f: → действия ролей." },
  { id: "start", x: 900, y: -40, icon: UserRound, color: "#f472b6", title: "Согласие и роль", tech: "152-ФЗ · contact · invite", simple: "Сначала согласие на обработку персональных данных, потом «Поделиться номером» — бот сам находит человека в учёте. Сотрудники входят по коду приглашения.", engineer: "pd_consent (версия, время) + событие аудита; без согласия текст не уходит в LLM и кнопки ролей не отдают данные. request_contact: проверка contact.user_id == from.id, сопоставление с учётом, хранится только sha256(space:номер) и маска. /privacy, /delete_me — отзыв согласия удаляет пространство пользователя." },
  { id: "menu", x: 900, y: 170, icon: LayoutGrid, color: "#60a5fa", title: "Меню роли", tech: "inline keyboard", simple: "У каждой роли свои кнопки: баланс и договор у водителя, брони у клиента, заявки у отделов.", engineer: "menu(sp) строит клавиатуру по роли; каждое действие — функция driver_action / client_action / staff_action / finance_action." },
  { id: "text", x: 900, y: 380, icon: MessageSquareText, color: "#c084fc", title: "Свободный текст", tech: "→ агент", simple: "Можно просто написать своими словами — вопрос или проблему.", engineer: "Текст без команды уходит агенту до основной транзакции (LLM не держит блокировку пространства)." },
  { id: "commands", x: 1140, y: 110, icon: ShieldCheck, color: "#f472b6", title: "Бизнес-команды", tech: "domain.command", simple: "Те же проверки, что и в кабинете: права роли, статус, защита от двойного нажатия.", engineer: "command(s, sp, action, payload, key='tg:'+update_id) — идемпотентность по update_id, аудит + outbox в одной транзакции." },
  { id: "db", x: 1380, y: 110, icon: Database, color: "#60a5fa", title: "Учёт", tech: "PostgreSQL 16", simple: "Деньги, договоры и заявки — в одном учёте с кабинетом.", engineer: "NUMERIC, EXCLUDE для броней; бот и кабинет видят одни и те же данные мгновенно." },
  { id: "agent", x: 1140, y: 380, icon: Bot, color: "#22d3ee", title: "AI-агент", tech: "tools по роли", simple: "Помощник отвечает по данным вашей роли или по регламентам.", engineer: "agent.run: tool calling ≤4 раундов, инструменты tools_for(role); лимит 10 AI-запросов/час на пространство." },
  { id: "rag", x: 1380, y: 300, icon: BookOpen, color: "#34d399", title: "Регламенты", tech: "RAG", simple: "Правила парка — ответ со ссылкой на документ.", engineer: "search_knowledge → pgvector + FTS → RRF; без источников — честное «не нашёл»." },
  { id: "draft", x: 1380, y: 470, icon: ClipboardCheck, color: "#f472b6", title: "Черновик заявки", tech: "human-in-the-loop", simple: "Заявку агент только готовит — создаёт её человек кнопкой «Подтвердить».", engineer: "create_ticket → черновик на 10 минут; кнопка agentconfirm:<id> → confirm() → обычная бизнес-команда." },
  { id: "notify", x: 1620, y: 110, icon: BellRing, color: "#fb923c", title: "Уведомления", tech: "outbox → notify", simple: "Сервис и менеджер получают сообщение о новой заявке в свой Telegram.", engineer: "Событие outbox → job notify → sendMessage только тем, кому объект виден по правам." },
  { id: "reply", x: 440, y: -40, icon: Reply, color: "#34d399", title: "Ответ", tech: "Bot API / эмулятор", simple: "Ответ с кнопками приходит в чат.", engineer: "_deliver: sendMessage / sendPhoto / sendDocument (HTML parse_mode); в эмуляторе те же сообщения сериализуются в JSON." },
];

const EDGES: FEdge[] = [
  { id: "tg-hook", from: "tg", to: "hook" },
  { id: "hook-queue", from: "hook", to: "queue" },
  { id: "queue-router", from: "queue", to: "router" },
  { id: "router-start", from: "router", to: "start" },
  { id: "router-menu", from: "router", to: "menu" },
  { id: "router-text", from: "router", to: "text" },
  { id: "menu-commands", from: "menu", to: "commands" },
  { id: "commands-db", from: "commands", to: "db" },
  { id: "db-notify", from: "db", to: "notify", label: "outbox" },
  { id: "text-agent", from: "text", to: "agent" },
  { id: "agent-rag", from: "agent", to: "rag" },
  { id: "agent-draft", from: "agent", to: "draft" },
  { id: "draft-commands", from: "draft", to: "commands", out: "t", in: "b", dashed: true, label: "«Подтвердить»" },
  { id: "router-reply", from: "router", to: "reply", out: "t", in: "r" },
  { id: "reply-tg", from: "reply", to: "tg", out: "l", in: "t" },
];

const back = (...ids: string[]) => ids.map((id) => ({ id, reverse: true }));
const IN = ["tg-hook", "hook-queue", "queue-router"];

type Sc = { id: string; icon: any; title: string; steps: (Omit<Frame, "key" | "label"> & { label: string; simple: string; eng: string })[] };
const SCENARIOS: Sc[] = [
  {
    id: "balance",
    icon: Wallet,
    title: "Водитель жмёт «Баланс»",
    steps: [
      { node: "tg", label: "Кнопка", simple: "Водитель нажимает «💰 Баланс и долг».", eng: "callback_query data=d:balance" },
      { node: "hook", edges: ["tg-hook"], label: "Вебхук", simple: "Сервер проверяет подпись Telegram.", eng: "secret_token ok, update_id новый" },
      { node: "queue", edges: ["hook-queue"], label: "Очередь", simple: "Нажатие стало задачей.", eng: "Job(kind=telegram)" },
      { node: "router", edges: ["queue-router"], label: "Роль", simple: "Бот узнаёт водителя по Telegram-аккаунту.", eng: "Space по tg_user, role=driver" },
      { node: "menu", edges: ["router-menu"], label: "Действие", simple: "Выбрано действие водителя «баланс».", eng: "driver_action('balance')" },
      { node: "commands", edges: ["menu-commands"], label: "Права", simple: "Считаются только договоры этого водителя.", eng: "report(s, sp) в scope роли" },
      { node: "db", edges: ["commands-db"], label: "Учёт", simple: "Цифры — из того же учёта, что видит собственник.", eng: "начисления − платежи, NUMERIC" },
      { node: "reply", edges: [...back("commands-db", "menu-commands", "router-menu"), "router-reply"], label: "Ответ", simple: "Бот присылает баланс и кнопки дальше.", eng: "sendMessage + inline keyboard" },
      { node: "tg", edges: ["reply-tg"], label: "В чате", simple: "Через секунду ответ в чате.", eng: "≈1 с от нажатия до ответа" },
    ],
  },
  {
    id: "question",
    icon: BookOpen,
    title: "Вопрос своими словами",
    steps: [
      { node: "tg", label: "Вопрос", simple: "«Какие документы нужны водителю?»", eng: "message.text" },
      { node: "queue", edges: IN.slice(0, 2), label: "Приём", simple: "Принято и поставлено в очередь.", eng: "webhook → Job" },
      { node: "router", edges: ["queue-router"], label: "Разбор", simple: "Это не кнопка — свободный текст.", eng: "нет '/' и callback → агент" },
      { node: "text", edges: ["router-text"], label: "Текст", simple: "Текст уходит помощнику.", eng: "agent_message(space, role, text)" },
      { node: "agent", edges: ["text-agent"], label: "Агент", simple: "Помощник решает искать в регламентах.", eng: "tool_call search_knowledge" },
      { node: "rag", edges: ["agent-rag"], label: "Регламенты", simple: "Находит нужные правила.", eng: "pgvector + FTS → RRF, порог 0.38" },
      { node: "reply", edges: [...back("agent-rag", "text-agent", "router-text"), "router-reply"], label: "Ответ", simple: "Ответ со ссылкой на источник.", eng: "answer + «Источники: …»" },
      { node: "tg", edges: ["reply-tg"], label: "В чате", simple: "Ответ в чате за несколько секунд.", eng: "2–6 с, стоимость в Usage" },
    ],
  },
  {
    id: "ticket",
    icon: Wrench,
    title: "Поломка → заявка",
    steps: [
      { node: "tg", label: "Сообщение", simple: "«Стучит подвеска, посмотрите»", eng: "message.text (в настоящем боте — можно с фото)" },
      { node: "router", edges: IN, label: "Разбор", simple: "Принято, это свободный текст.", eng: "webhook → Job → handle()" },
      { node: "agent", edges: ["router-text", "text-agent"], label: "Агент", simple: "Помощник понимает: это проблема с машиной.", eng: "tool_call create_ticket" },
      { node: "draft", edges: ["agent-draft"], label: "Черновик", simple: "Готовит заявку, но не создаёт её сам.", eng: "черновик 10 мин, кнопка agentconfirm" },
      { node: "commands", edges: ["draft-commands"], label: "Подтверждение", simple: "Водитель нажимает «Подтвердить» — заявка создаётся.", eng: "confirm() → command('ticket.create')" },
      { node: "db", edges: ["commands-db"], label: "Учёт", simple: "Заявка сразу видна сервису в кабинете.", eng: "Item(kind=ticket), SLA от приоритета" },
      { node: "notify", edges: ["db-notify"], label: "Сервис", simple: "Сервис получает уведомление в свой Telegram.", eng: "outbox → notify → sendMessage" },
    ],
  },
  {
    id: "start",
    icon: UserPlus,
    title: "Новый пользователь",
    steps: [
      { node: "tg", label: "/start", simple: "Человек впервые открывает бота.", eng: "message /start" },
      { node: "router", edges: IN, label: "Новый", simple: "Бот создаёт ему личное пространство.", eng: "claim_space() из пула — мгновенно" },
      { node: "start", edges: ["router-start"], label: "Согласие", simple: "Бот просит согласие на обработку персональных данных (152-ФЗ).", eng: "consent_msg → pd:yes → pd_consent + аудит" },
      { node: "reply", edges: [...back("router-start"), "router-reply"], label: "Номер", simple: "Просит поделиться номером телефона.", eng: "ReplyKeyboard request_contact=True" },
      { node: "start", edges: [{ id: "reply-tg" }, "router-start"], label: "Роль по учёту", simple: "Находит человека в учёте и открывает меню его роли. Номер хранится только как хеш.", eng: "match_contact → role; phone_hash + phone_mask, сырой номер не сохраняется" },
      { node: "reply", edges: [...back("router-start"), "router-reply"], label: "Меню", simple: "Показывает меню его роли.", eng: "menu(sp)" },
      { node: "tg", edges: ["reply-tg"], label: "В чате", simple: "Можно пользоваться.", eng: "" },
    ],
  },
];

export function BotFlow({ data, openEmulator }: { data: Data; openEmulator: () => void }) {
  const eng = useEngineer();
  const [sc, setSc] = useState<Sc | null>(null);
  const [run, setRun] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const log = useQuery({ queryKey: ["under-log", data.session.role], queryFn: () => api("/under/log"), refetchInterval: 5000 });
  const feed = (log.data?.rows || []).filter((r: any) => r.type === "webhook" || r.type === "telegram" || r.type === "telegram_sim").slice(0, 8);
  const frames: Frame[] = useMemo(() => (sc?.steps || []).map((s, i) => ({ ...s, key: sc!.id + i, hold: 1400 })), [sc]);
  const replay = useReplay(frames, sc ? sc.id + run : "none");
  const step = replay.current ? sc?.steps[replay.pos] : null;
  const node = NODES.find((n) => n.id === (selected || step?.node || ""));
  const nodes: FNode[] = NODES.map((n) => ({
    ...n,
    sub: eng ? n.tech : undefined,
    size: n.id === "router" ? "lg" : "md",
    state: sc ? replay.states[n.id] : undefined,
    dim: !!sc && !frames.some((f) => f.node === n.id),
  }));
  const start = (s: Sc) => {
    setSelected(null);
    setSc(s);
    setRun((r) => r + 1);
  };
  // Someone who came by a link sees the scheme in motion at once: the first scenario plays by itself.
  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = setTimeout(() => setSc((cur) => cur ?? (setRun((r) => r + 1), SCENARIOS[0])), 900);
    return () => clearTimeout(t);
  }, []);
  return (
    <div className="k-stage">
      <div className="k-canvas-wrap">
        <div className="k-canvas-head">
          <div className="k-scenarios">
            {SCENARIOS.map((s) => (
              <button key={s.id} className={sc?.id === s.id ? "active" : ""} onClick={() => start(s)}>
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
          selected={selected}
          onSelect={setSelected}
          scene={sc?.id + "-" + replay.done}
        />
        {step && (
          <div className="k-caption" key={replay.pos}>
            <span>
              {replay.pos + 1}/{frames.length}
            </span>
            <p>{eng ? step.eng || step.simple : step.simple}</p>
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
                <span className="k-eyebrow">{eng ? node.tech : "Шаг обработки"}</span>
                <h3>{node.title}</h3>
              </div>
            </div>
            <p className="k-lead">{eng ? node.engineer : node.simple}</p>
          </>
        ) : (
          <>
            <span className="k-eyebrow">Telegram-бот</span>
            <h3 className="k-h">Один бот — три типа пользователей</h3>
            <p className="k-lead">
              <Say
                simple="Водители, клиенты и отделы пишут в одного бота. Бот не отдельная программа: он пользуется теми же ролями, правилами и учётом, что и кабинет."
                eng="Вебхук → очередь → telegram.handle(): роль из пространства, действия через domain.command с ключом идемпотентности tg:update_id, свободный текст — агент с ролевыми инструментами. Транспорт отделён от логики: Bot API или веб-эмулятор."
              />
            </p>
          </>
        )}
        {sc && (
          <Section title={sc.title}>
            <ol className="k-steps">
              {sc.steps.map((s, i) => (
                <li key={i} className={i === replay.pos ? "now" : i < replay.pos || replay.done ? "done" : ""} onClick={() => replay.seek(i)}>
                  <b>{s.label}</b>
                  <span>{eng ? s.eng || s.simple : s.simple}</span>
                </li>
              ))}
            </ol>
          </Section>
        )}
        {!sc && (
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
        <Section title="Сообщения бота в этой сессии">
          {feed.length ? (
            <div className="k-runs">
              {feed.map((r: any) => (
                <button key={r.id} onClick={() => setSelected("router")}>
                  <i className="k-dot done" />
                  <span>{r.title}</span>
                  <small>
                    {new Date(r.at).toLocaleTimeString("ru-RU", { timeZone: "Europe/Moscow" })} · {r.role || data.session.roles[data.session.role]}
                  </small>
                </button>
              ))}
            </div>
          ) : (
            <p className="k-hint">Пока пусто — напишите боту в эмуляторе или в Telegram.</p>
          )}
          <button className="k-btn primary wide" onClick={openEmulator}>
            Открыть эмулятор бота
            <ArrowRight size={15} />
          </button>
        </Section>
      </aside>
      <Timeline frames={frames} replay={replay} empty="Выберите сценарий над схемой — шаги появятся здесь" />
    </div>
  );
}
