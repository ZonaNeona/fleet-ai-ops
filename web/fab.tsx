import { Sparkles } from "lucide-react";
import { CREDIT } from "./lib";

/** The AI assistant button on every screen: bottom right, with a shimmering Gemini-style border. */
export function AskFab({ onClick, hidden }: { onClick: () => void; hidden?: boolean }) {
  if (hidden) return null;
  return (
    <button className="ask-fab" onClick={onClick} aria-label="Спросить AI-помощника" title="AI-помощник парка">
      <span className="ask-fab-glow" aria-hidden />
      <span className="ask-fab-body">
        <span className="ask-fab-icon" aria-hidden>
          <Sparkles size={19} strokeWidth={2} />
          <i />
        </span>
        <span className="ask-fab-text">
          <b>Спросить AI</b>
          <small>агент с данными парка</small>
        </span>
      </span>
    </button>
  );
}

/** Caption: concept and prototype, author. */
export function Credit({ className = "" }: { className?: string }) {
  return (
    <span className={"credit " + className}>
      Концепт и прототип · автор <b>{CREDIT.author}</b>
    </span>
  );
}
