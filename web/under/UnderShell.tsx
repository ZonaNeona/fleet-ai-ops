import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Code2, Eye, CarFront } from "lucide-react";
import { Data, Row } from "../lib";
import { LevelCtx } from "./kit";
import { AIPanel } from "../views";
import { AskFab, Credit } from "../fab";
import { SystemMap } from "./SystemMap";
import { RagView } from "./RagView";
import { AgentView } from "./AgentView";
import { N8nView } from "./N8nView";
import { LogView } from "./LogView";
import { BotFlow } from "./BotFlow";
import { DocsView } from "./DocsView";
import { McpView } from "./McpView";
import { OpsView } from "./OpsView";
import { RobotView } from "./RobotView";
import { ModeSwitch, SECTIONS } from "./mode";

type Ctx = { job?: string; prompt?: string; run?: string };

export function UnderShell({
  data,
  section,
  setSection,
  role,
  onSwitch,
  openRow,
  openBot,
  openInbox,
}: {
  data: Data;
  section: string;
  setSection: (s: string) => void;
  role: (r: string) => void;
  onSwitch: (m: "product" | "under", e: React.MouseEvent) => void;
  openRow: (r: Row) => void;
  openBot: () => void;
  openInbox: () => void;
}) {
  const [engineer, setEngineer] = useState(() => {
    try {
      return localStorage.getItem("ec-level") === "eng";
    } catch {
      return false;
    }
  });
  const [ctx, setCtx] = useState<Record<string, Ctx>>({});
  const [ai, setAi] = useState(false);
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => (await fetch("/api/health")).json(),
    refetchInterval: 30000,
  });
  useEffect(() => {
    try {
      localStorage.setItem("ec-level", engineer ? "eng" : "simple");
    } catch {}
  }, [engineer]);
  useEffect(() => setCtx({}), [data.session.role]);
  const go = (s: string, opts: Ctx = {}) => {
    setCtx((c) => ({ ...c, [s]: { ...opts } }));
    setSection(s);
  };
  const info = SECTIONS.find((s) => s[0] === section) || SECTIONS[0];
  const remember = (s: string) => (id: string, prompt: string) =>
    setCtx((c) => ({ ...c, [s]: { job: id, prompt } }));
  return (
    <LevelCtx.Provider value={engineer}>
      <div className="k-shell">
        <header className="k-top">
          <div className="k-brand">
            <span className="k-logo">
              <CarFront size={18} />
            </span>
            <div>
              <strong>Таксопарк</strong>
              <span>под капотом · инженерная консоль</span>
            </div>
          </div>
          <div className="k-crumb">
            {(() => {
              const I = info[3];
              return <I size={15} />;
            })()}
            <strong>{info[1]}</strong>
            <span>{info[2]}</span>
          </div>
          <div className="k-top-right">
            <div className="k-level" role="group" aria-label="Уровень объяснения">
              <button aria-pressed={!engineer} onClick={() => setEngineer(false)} title="Простыми словами">
                <Eye size={14} />
                <span>Просто</span>
              </button>
              <button aria-pressed={engineer} onClick={() => setEngineer(true)} title="Для инженера">
                <Code2 size={14} />
                <span>Инженер</span>
              </button>
            </div>
            <select
              className="k-role"
              aria-label="Демонстрационная роль"
              value={data.session.role}
              onChange={(e) => role(e.target.value)}
            >
              {Object.entries(data.session.roles).map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
            <ModeSwitch mode="under" onSwitch={onSwitch} />
          </div>
        </header>
        <nav className="k-rail" aria-label="Разделы">
          {SECTIONS.map(([id, label, hint, Icon]) => (
            <button key={id} className={section === id ? "active" : ""} onClick={() => setSection(id)} title={hint}>
              <Icon size={19} />
              <span>{label}</span>
            </button>
          ))}
          <div className="k-rail-status">
            <i className={health.data?.status === "ok" ? "ok" : ""} />
            <span>{health.data?.status === "ok" ? "online" : "…"}</span>
          </div>
        </nav>
        <main className="k-main" key={section}>
          {section === "map" && <SystemMap go={(s, prompt) => go(s, { prompt })} />}
          {section === "bot" && <BotFlow data={data} openEmulator={openBot} />}
          {section === "rag" && (
            <RagView data={data} initialJob={ctx.rag?.job} initialPrompt={ctx.rag?.prompt} onStart={remember("rag")} />
          )}
          {section === "agent" && (
            <AgentView data={data} initialJob={ctx.agent?.job} initialPrompt={ctx.agent?.prompt} onStart={remember("agent")} />
          )}
          {section === "n8n" && <N8nView data={data} openRow={openRow} initialRun={ctx.n8n?.run} />}
          {section === "docs" && <DocsView data={data} openInbox={openInbox} />}
          {section === "mcp" && <McpView />}
          {section === "ops" && <OpsView />}
          {section === "robot" && <RobotView />}
          {section === "log" && <LogView data={data} go={go} />}
        </main>
        <footer className="k-foot">
          <Credit /> · учебные данные · RAG, агент, документы и интеграции — реальные вызовы вашей сессии, сценарии бота — пошаговая схема
        </footer>
        <AskFab onClick={() => setAi(true)} hidden={ai} />
        {/* помощник тот же, что в продукте, но в тёмных токенах консоли */}
        <div ref={setHost} data-theme="dark" className="k-ai-host" />
        {ai && host && <AIPanel data={data} target={null} onClose={() => setAi(false)} container={host} />}
      </div>
    </LevelCtx.Provider>
  );
}
