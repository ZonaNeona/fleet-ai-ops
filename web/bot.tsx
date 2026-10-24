import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CarFront,
  Send,
  Paperclip,
  Mic,
  Square,
  FileText,
  Bot as BotIcon,
  CarTaxiFront,
  KeyRound,
  Building2,
  ArrowUpRight,
  Cpu,
  ShieldCheck,
  Workflow,
  MessageSquareText,
  X,
  LoaderCircle,
} from "lucide-react";
import { api, Data } from "./lib";

type Btn = {
  text: string;
  data?: string | null;
  url?: string | null;
  app?: boolean;
  app_url?: string | null;
};
type Msg = {
  id?: string;
  edit_target?: string;
  from: "me" | "bot";
  text: string;
  kb?: Btn[][];
  photo?: string;
  document?: { name: string; size: number; data?: string };
  at: number;
};

/* Разрешаем только разметку, которую формирует сам бот (parse_mode=HTML Telegram). */
function safeHtml(text: string) {
  return text.replace(
    /<(?!\/?(b|i|u|s|code|a)(\s+href="https?:[^"<>]*")?\s*>)[^>]*>/g,
    "",
  );
}

const ROLES = [
  {
    id: "driver",
    icon: CarTaxiFront,
    title: "Водитель такси",
    items: [
      "Баланс, долг и начисления",
      "Своя машина и договор в PDF",
      "Штрафы ГИБДД — через интеграцию n8n",
      "Выходной в один клик",
      "Поломка → заявка, можно с фото",
      "Вопросы по правилам — ответ по регламентам",
    ],
  },
  {
    id: "client",
    icon: KeyRound,
    title: "Клиент проката",
    items: [
      "Свободные машины на даты",
      "Бронь без пересечений",
      "Мои брони и статусы",
      "Обращение в поддержку",
    ],
  },
  {
    id: "manager",
    icon: Building2,
    title: "Отделы парка",
    items: [
      "Вход по коду приглашения отдела",
      "В демо доступно в веб-кабинете",
      "Менеджер: документы, подтверждение брони и выдача",
      "Сервис: заявки и ремонты; финансы: расчёты",
      "Собственник: мобильный дашборд",
    ],
  },
] as const;

export function BotPage({
  data,
  bot,
  openCabinet,
}: {
  data: Data;
  bot?: string;
  openCabinet: () => void;
}) {
  const qc = useQueryClient();
  const storeKey = "ec-bot-" + data.session.id;
  const [msgs, setMsgs] = useState<Msg[]>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(storeKey) || "[]");
    } catch {
      return [];
    }
  });
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [recording, setRecording] = useState<MediaRecorder | null>(null);
  // Microphone: the recording goes through the same speech-to-text as Telegram voice notes, then as a message.
  async function voice() {
    if (recording) {
      recording.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const parts: Blob[] = [];
      rec.ondataavailable = (e) => parts.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(null);
        const form = new FormData();
        form.append("file", new Blob(parts, { type: rec.mimeType }), "voice.webm");
        setPending(true);
        try {
          const r = await api<{ text: string }>("/voice", { method: "POST", body: form });
          setPending(false);
          await send({ text: r.text, voice: true });
        } catch (e: any) {
          setPending(false);
          setError(e.message);
        }
      };
      rec.start();
      setRecording(rec);
      setTimeout(() => rec.state === "recording" && rec.stop(), 60000);
    } catch {
      setError("Нет доступа к микрофону");
    }
  }
  const [error, setError] = useState("");
  const [wire, setWire] = useState<{ vk: any[]; max: any[] } | null>(null);
  const [wireTab, setWireTab] = useState<"vk" | "max">("vk");
  const feed = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  const [miniUrl, setMiniUrl] = useState("");
  const [miniReady, setMiniReady] = useState(false);
  const [mainButton, setMainButton] = useState<{
    text: string;
    disabled?: boolean;
    busy?: boolean;
  } | null>(null);
  const [miniBack, setMiniBack] = useState(false);
  useEffect(() => {
    setMiniUrl("");
    setMainButton(null);
  }, [data.session.id, data.session.role]);
  useEffect(() => {
    const sendTheme = () =>
      frame.current?.contentWindow?.postMessage(
        {
          channel: "fleet-miniapp-v1",
          type: "theme",
          value:
            document.documentElement.dataset.theme === "dark"
              ? "dark"
              : "light",
        },
        location.origin,
      );
    const receive = (e: MessageEvent) => {
      if (
        e.origin !== location.origin ||
        e.source !== frame.current?.contentWindow ||
        e.data?.channel !== "fleet-miniapp-v1"
      )
        return;
      if (e.data.type === "ready") {
        setMiniReady(true);
        sendTheme();
      }
      if (e.data.type === "main-button") setMainButton(e.data.value);
      if (e.data.type === "back-button") setMiniBack(!!e.data.value);
      if (e.data.type === "close") setMiniUrl("");
      if (e.data.type === "data-changed" || e.data.type === "close")
        qc.invalidateQueries();
    };
    const themeObserver = new MutationObserver(sendTheme);
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    window.addEventListener("message", receive);
    return () => {
      window.removeEventListener("message", receive);
      themeObserver.disconnect();
    };
  }, [qc]);
  const toMini = (type: string) =>
    frame.current?.contentWindow?.postMessage(
      { channel: "fleet-miniapp-v1", type },
      location.origin,
    );
  useEffect(() => {
    try {
      sessionStorage.setItem(storeKey, JSON.stringify(msgs.slice(-60)));
    } catch {}
    feed.current?.scrollTo({
      top: feed.current.scrollHeight,
      behavior: "smooth",
    });
  }, [msgs, pending, storeKey]);

  async function send(payload: {
    text?: string;
    callback?: string;
    message_id?: string;
    voice?: boolean;
  }) {
    if (pending) return;
    setError("");
    if (payload.text)
      setMsgs((m) => [
        ...m,
        { from: "me", text: (payload.voice ? "🎤 " : "") + payload.text!, at: Date.now() },
      ]);
    setPending(true);
    try {
      const { voice: _voice, ...body } = payload;
      const { id } = await api("/bot/sim", {
        method: "POST",
        body: JSON.stringify(body),
      });
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, i < 5 ? 400 : 900));
        const r = await api("/bot/sim/" + id);
        if (r.state === "done") {
          if (r.result.channels) setWire(r.result.channels);
          const out: Msg[] = (r.result.messages || []).map((x: any) => ({
            ...x,
            from: "bot",
            at: Date.now(),
          }));
          setMsgs((messages) => {
            const next = [...messages];
            for (const item of out) {
              const index = item.edit_target
                ? next.findIndex((x) => x.id === item.edit_target)
                : -1;
              if (index >= 0) next[index] = item;
              else if (!item.id || !next.some((x) => x.id === item.id))
                next.push(item);
            }
            return next;
          });
          if (r.result.role && r.result.role !== data.session.role) {
            qc.invalidateQueries({ queryKey: ["session"] });
            qc.invalidateQueries({ queryKey: ["bootstrap"] });
          }
          return;
        }
        if (r.state === "failed")
          throw new Error(
            r.result?.error || "Бот не смог обработать сообщение",
          );
      }
      throw new Error("Бот не ответил вовремя");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setPending(false);
    }
  }
  const press = (b: Btn, messageId?: string) => {
    if (b.app) {
      if (!["client", "driver"].includes(data.session.role))
        return openCabinet();
      const target = new URL(b.app_url || "/?tg=1", location.origin);
      setMiniReady(false);
      setMainButton(null);
      setMiniBack(false);
      setMiniUrl(
        "/?tg=1&emulator=1" +
          (target.hash.startsWith("#tg/")
            ? target.hash
            : "#tg/" + (data.session.role === "driver" ? "driver" : "catalog")),
      );
      return;
    }
    if (b.url) return window.open(b.url, "_blank", "noopener");
    if (b.data) send({ callback: b.data, message_id: messageId });
  };

  return (
    <div className="botpage">
      <section className="bot-info">
        <div className="bot-hero card">
          <span className="eyebrow">TELEGRAM · ТРИ ТИПА ПОЛЬЗОВАТЕЛЕЙ</span>
          <h2>Один бот для водителей, клиентов и отделов</h2>
          <p>
            Бот — ещё один вход в ту же систему: те же роли, права,
            бизнес-команды и учёт, что и в кабинете. Справа — эмулятор: он
            вызывает тот же код, что и настоящий бот, только ответ приходит
            сюда, а не в Telegram.
          </p>
          <div className="bot-hero-actions">
            {bot && (
              <a
                className="button primary"
                href={`https://t.me/${bot}`}
                target="_blank"
                rel="noreferrer"
              >
                <Send size={16} /> Открыть @{bot}
              </a>
            )}
            <button
              className="button secondary"
              onClick={() => send({ text: "/start" })}
              disabled={pending}
            >
              <MessageSquareText size={16} /> Начать в эмуляторе
            </button>
          </div>
        </div>
        <div className="bot-roles">
          {ROLES.map((r) => (
            <div className="bot-role card" key={r.id}>
              <div className="bot-role-head">
                <span>
                  <r.icon size={18} />
                </span>
                <h3>{r.title}</h3>
              </div>
              <ul>
                {r.items.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
              <button
                className="text-button"
                disabled={pending}
                onClick={() => send({ callback: "role:" + r.id })}
              >
                Войти в чате как{" "}
                {r.id === "manager" ? "менеджер" : r.title.toLowerCase()}{" "}
                <ArrowUpRight size={14} />
              </button>
            </div>
          ))}
        </div>
        <div className="bot-how card">
          <h3>Как это устроено</h3>
          <ol>
            <li>
              <Workflow size={15} /> Telegram → вебхук с secret_token → задание
              в очереди: ответ не теряется при перезапуске.
            </li>
            <li>
              <KeyRound size={15} /> Без регистрации: /start → выбор роли. У
              водителя, клиента, отделов и собственника свои кнопки и права.
            </li>
            <li>
              <ShieldCheck size={15} /> Роль и права проверяет сервер; действия
              идут через те же команды, что и в кабинете, с ключом
              идемпотентности.
            </li>
            <li>
              <BotIcon size={15} /> Свободный текст — AI-агент с инструментами и
              поиском по регламентам; заявки — только после кнопки
              «Подтвердить».
            </li>
            <li>
              <Cpu size={15} /> Путь каждого сообщения виден в «Под капотом» →
              Журнал.
            </li>
          </ol>
          <p className="muted">
            В кабинете внутри телефона можно загрузить учебные документы и
            фотографии. Реальные списания отключены.
          </p>
        </div>
        <div className="bot-how card bot-wire">
          <h3>Тот же сценарий в VK и MAX</h3>
          <p className="muted">
            Ядро бота одно: событие VK или MAX приводится к тому же виду, что апдейт Telegram, а ответ — к вызову API
            канала. Нажмите кнопку в телефоне — здесь появится, что получил бы каждый канал.
          </p>
          <div className="tabs">
            {(["vk", "max"] as const).map((c) => (
              <button key={c} className={wireTab === c ? "active" : ""} onClick={() => setWireTab(c)}>
                {c === "vk" ? "VK · messages.send" : "MAX · POST /messages"}
              </button>
            ))}
          </div>
          <pre className="bot-wire-json">{wire ? JSON.stringify(wire[wireTab], null, 2).slice(0, 2400) : "Ответов ещё не было."}</pre>
        </div>
      </section>

      <section className="phone-wrap" aria-label="Эмулятор Telegram-бота">
        <div className="phone">
          <div className="phone-notch" />
          <header className="tg-head">
            <ArrowLeft size={20} />
            <span className="tg-avatar">
              <CarFront size={18} />
            </span>
            <div>
              <strong>Таксопарк · бот</strong>
              <small>{pending ? "печатает…" : "бот"}</small>
            </div>
          </header>
          <div className="tg-feed" ref={feed}>
            {!msgs.length && (
              <div className="tg-intro">
                <span className="tg-avatar big">
                  <CarFront size={30} />
                </span>
                <strong>Что умеет этот бот?</strong>
                <p>
                  Баланс и договор водителя, бронирование для клиентов, заявки и
                  согласования для отделов. Пишите своими словами — бот найдёт
                  ответ в правилах или подготовит заявку.
                </p>
                <small>Учебный концепт, не официальный бот.</small>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={"tg-msg " + m.from}>
                <div className="tg-bubble">
                  {m.photo && (
                    <img
                      src={m.photo}
                      alt=""
                      loading="lazy"
                      onError={(e) => (e.currentTarget.style.display = "none")}
                    />
                  )}
                  {m.document && (
                    <a
                      className="tg-doc"
                      href={m.document.data}
                      download={m.document.name}
                    >
                      <FileText size={22} />
                      <span>
                        {m.document.name}
                        <small>
                          {Math.round(m.document.size / 1024)} КБ · PDF
                        </small>
                      </span>
                    </a>
                  )}
                  {m.text && (
                    <div
                      className="tg-text"
                      dangerouslySetInnerHTML={{ __html: safeHtml(m.text) }}
                    />
                  )}
                  <time>
                    {new Date(m.at).toLocaleTimeString("ru-RU", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </time>
                </div>
                {m.kb && m.kb.length > 0 && (
                  <div className="tg-kb">
                    {m.kb.map((row, j) => (
                      <div key={j}>
                        {row.map((b, k) => (
                          <button
                            key={k}
                            onClick={() => press(b, m.id)}
                            disabled={pending && !b.url && !b.app}
                          >
                            {b.text}
                            {(b.url || b.app) && <ArrowUpRight size={11} />}
                          </button>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {pending && (
              <div className="tg-msg bot">
                <div className="tg-bubble tg-typing">
                  <i />
                  <i />
                  <i />
                </div>
              </div>
            )}
            {error && <div className="tg-error">{error}</div>}
          </div>
          {msgs.length ? (
            <form
              className="tg-input"
              onSubmit={(e) => {
                e.preventDefault();
                if (text.trim()) send({ text: text.trim() });
                setText("");
              }}
            >
              <button
                type="button"
                className="tg-menu"
                onClick={() => send({ text: "/menu" })}
                disabled={pending}
              >
                Меню
              </button>
              <input
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Сообщение"
                maxLength={1500}
              />
              {text.trim() ? (
                <button
                  type="submit"
                  className="tg-send"
                  aria-label="Отправить"
                  disabled={pending}
                >
                  <Send size={18} />
                </button>
              ) : (
                <>
                  <span className="tg-clip" title="Фото — в настоящем боте">
                    <Paperclip size={19} />
                  </span>
                  <button
                    type="button"
                    className={"tg-send tg-mic" + (recording ? " on" : "")}
                    aria-label={recording ? "Остановить запись" : "Голосовое сообщение"}
                    title={recording ? "Остановить и отправить" : "Голосовое: распознаётся моделью и уходит боту текстом"}
                    disabled={pending}
                    onClick={voice}
                  >
                    {recording ? <Square size={16} /> : <Mic size={18} />}
                  </button>
                </>
              )}
            </form>
          ) : (
            <button
              className="tg-start"
              onClick={() => send({ text: "/start" })}
              disabled={pending}
            >
              СТАРТ
            </button>
          )}
          {miniUrl && (
            <div
              className="phone-mini"
              role="dialog"
              aria-label="Mini App в эмуляторе"
            >
              <div className="phone-mini-bar">
                <button
                  onClick={() =>
                    miniBack ? toMini("back-click") : setMiniUrl("")
                  }
                  aria-label="Назад в Mini App"
                >
                  <ArrowLeft size={18} />
                </button>
                <span>
                  Таксопарк <small>мини-приложение</small>
                </span>
                <button
                  aria-label="Закрыть Mini App"
                  onClick={() => {
                    setMiniUrl("");
                    qc.invalidateQueries();
                  }}
                >
                  <X size={19} />
                </button>
              </div>
              <iframe
                ref={frame}
                src={miniUrl}
                title="Кабинет таксопарка"
                allow="geolocation; camera"
              />
              {!miniReady && (
                <div className="phone-mini-loading">
                  <LoaderCircle size={24} className="mini-spin" /> Открываем
                  кабинет…
                </div>
              )}
              {mainButton && (
                <div className="phone-mini-action">
                  <button
                    disabled={mainButton.disabled || mainButton.busy}
                    onClick={() => toMini("main-click")}
                  >
                    {mainButton.busy && (
                      <LoaderCircle size={16} className="mini-spin" />
                    )}
                    {mainButton.text}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
        {msgs.length > 0 && (
          <button
            className="text-button phone-reset"
            onClick={() => {
              setMsgs([]);
              setError("");
            }}
          >
            Очистить чат
          </button>
        )}
      </section>
    </div>
  );
}
