import { useEffect, useState } from "react";
import { CornerDownLeft, LoaderCircle } from "lucide-react";

/** Командная строка консоли: вопрос + подсказки. */
export function PromptBar({
  busy,
  onRun,
  suggestions,
  initial,
  placeholder,
  status,
  disabled,
}: {
  busy: boolean;
  onRun: (prompt: string) => void;
  suggestions: string[];
  initial?: string;
  placeholder: string;
  status?: string;
  disabled?: boolean;
}) {
  const [prompt, setPrompt] = useState(initial || "");
  useEffect(() => {
    if (initial) setPrompt(initial);
  }, [initial]);
  const send = (p = prompt) => {
    if (busy || p.trim().length < 2 || disabled) return;
    setPrompt(p);
    onRun(p.trim());
  };
  return (
    <div className="k-prompt">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <span className="k-prompt-caret">›</span>
        <input
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          maxLength={2000}
          placeholder={placeholder}
          aria-label="Вопрос"
        />
        <button className="k-btn primary" disabled={busy || prompt.trim().length < 2 || disabled}>
          {busy ? <LoaderCircle size={15} className="spin" /> : <CornerDownLeft size={15} />}
          {busy ? "Выполняется" : "Запустить"}
        </button>
      </form>
      <div className="k-chips">
        {status ? (
          <span className="k-live">
            <i />
            {status}
          </span>
        ) : (
          suggestions.map((s) => (
            <button key={s} onClick={() => send(s)} disabled={busy || disabled}>
              {s}
            </button>
          ))
        )}
      </div>
    </div>
  );
}
