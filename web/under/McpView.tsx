import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Copy, KeyRound, Plug, Play } from "lucide-react";
import { api } from "../lib";
import { Json, Say, Section, useEngineer } from "./kit";

/* MCP: тот же реестр инструментов, что у встроенного агента, — для Claude Desktop, Cursor и других клиентов. */
export function McpView() {
  const eng = useEngineer();
  const tools = useQuery({ queryKey: ["mcp-tools"], queryFn: () => api<any>("/mcp/tools") });
  const [key, setKey] = useState("");
  const [probe, setProbe] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const url = key ? `${location.origin}/api/mcp?key=${key}` : `${location.origin}/api/mcp?key=…`;
  const desktop = JSON.stringify(
    { mcpServers: { "fleet-demo": { command: "npx", args: ["-y", "mcp-remote", url] } } },
    null,
    2,
  );
  const cursor = JSON.stringify({ mcpServers: { "fleet-demo": { url } } }, null, 2);

  const create = async () => {
    setBusy(true);
    try {
      setKey((await api<any>("/mcp/key", { method: "POST", body: "{}" })).key);
    } finally {
      setBusy(false);
    }
  };
  const call = async (method: string, params?: any) => {
    setBusy(true);
    try {
      const r = await fetch(`/api/mcp?key=${key}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
        body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method, params }),
      });
      setProbe({ request: { method, params }, status: r.status, response: await r.json() });
    } finally {
      setBusy(false);
    }
  };
  const copy = (text: string) => navigator.clipboard?.writeText(text);

  return (
    <div className="k-stage k-mcp">
      <div className="k-mcp-main">
        <span className="k-eyebrow">MCP · Model Context Protocol</span>
        <h3 className="k-h">Подключите своего ИИ-ассистента к таксопарку</h3>
        <p className="k-lead">
          <Say
            simple="Claude Desktop, Cursor или другой ассистент получает те же инструменты, что и встроенный агент: машины, договоры, экономика, регламенты, Битрикс24. Ключ привязан к вашему демо-пространству: черновик заявки, созданный ассистентом, появится у вас в кабинете и будет ждать подтверждения."
            eng="Streamable HTTP (спецификация 2025-06-18), JSON-RPC без сессий: initialize, tools/list, tools/call. Схемы инструментов генерируются из app/agent.py — одного реестра для встроенного агента и MCP. Ключ на 24 часа, роль owner, не больше 20 вызовов в минуту; есть stdio-вариант для локальных IDE: python -m app.mcp."
          />
        </p>

        <div className="k-mcp-key">
          {key ? (
            <>
              <code>{url}</code>
              <button className="k-btn" onClick={() => copy(url)}>
                <Copy size={14} /> Копировать
              </button>
            </>
          ) : (
            <button className="k-btn primary" disabled={busy} onClick={create}>
              <KeyRound size={15} /> Создать ключ на 24 часа
            </button>
          )}
        </div>

        <Section title="Claude Desktop — claude_desktop_config.json">
          <pre className="k-pre">{desktop}</pre>
          <button className="k-btn" onClick={() => copy(desktop)}>
            <Copy size={14} /> Копировать
          </button>
        </Section>
        <Section title="Cursor и клиенты с HTTP-транспортом — mcp.json">
          <pre className="k-pre">{cursor}</pre>
        </Section>
        <p className="k-hint">
          Попробуйте спросить ассистента: «Какие три машины дают самый низкий результат?» или «Где зависли кандидаты в
          найме?»
        </p>
      </div>

      <aside className="k-inspector">
        <span className="k-eyebrow">Живой список инструментов · роль {tools.data?.role}</span>
        <div className="k-checks">
          {(tools.data?.tools || []).map((t: any) => (
            <div key={t.name} className="ok">
              <b>
                <Plug size={12} /> {t.name}
              </b>
              <small>{t.description}</small>
              {eng && <small>параметры: {Object.keys(t.inputSchema?.properties || {}).join(", ") || "нет"}</small>}
            </div>
          ))}
        </div>
        <Section title="Проверить сервер прямо отсюда">
          <div className="k-mcp-probe">
            <button
              className="k-btn"
              disabled={!key || busy}
              onClick={() =>
                call("initialize", {
                  protocolVersion: "2025-06-18",
                  capabilities: {},
                  clientInfo: { name: "console", version: "1" },
                })
              }
            >
              <Play size={13} /> initialize
            </button>
            <button className="k-btn" disabled={!key || busy} onClick={() => call("tools/list")}>
              <Play size={13} /> tools/list
            </button>
            <button
              className="k-btn"
              disabled={!key || busy}
              onClick={() => call("tools/call", { name: "vehicle_economics", arguments: { worst: 3 } })}
            >
              <Play size={13} /> tools/call
            </button>
          </div>
          {!key && <p className="k-hint">Сначала создайте ключ.</p>}
          {probe && <Json value={probe} max={6000} />}
        </Section>
      </aside>
    </div>
  );
}
