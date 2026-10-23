import { Network, BookOpen, Bot, Workflow, TerminalSquare, Cpu, LayoutDashboard, Send } from "lucide-react";

/* Лёгкая часть контура «Под капотом»: нужна шапке продукта, поэтому не тянет за собой холсты. */

export const SECTIONS = [
  ["map", "Карта системы", "Как устроено", Network],
  ["bot", "Бот", "Telegram · три роли", Send],
  ["rag", "RAG", "Поиск по регламентам", BookOpen],
  ["agent", "Агент", "Инструменты и права", Bot],
  ["n8n", "Интеграции", "n8n · 1С · сверка", Workflow],
  ["log", "Журнал", "Живая лента", TerminalSquare],
] as const;

/** Переключатель контуров в шапке: «Продукт ⇄ Под капотом». */
export function ModeSwitch({
  mode,
  onSwitch,
}: {
  mode: "product" | "under";
  onSwitch: (m: "product" | "under", e: React.MouseEvent) => void;
}) {
  return (
    <div className={"mode-switch " + mode} role="group" aria-label="Контур">
      <span className="mode-pill" aria-hidden />
      <button
        aria-pressed={mode === "product"}
        aria-label="Продукт"
        title="Продукт — рабочий контур"
        onClick={(e) => mode !== "product" && onSwitch("product", e)}
      >
        <LayoutDashboard size={15} />
        <span>Продукт</span>
      </button>
      <button
        aria-pressed={mode === "under"}
        aria-label="Под капотом"
        title="Под капотом — как это работает"
        onClick={(e) => mode !== "under" && onSwitch("under", e)}
      >
        <Cpu size={15} />
        <span>Под капотом</span>
      </button>
    </div>
  );
}

