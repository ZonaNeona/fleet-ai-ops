import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { api } from "../lib";

/** Черновик действия агента: заявка создаётся только после явного подтверждения человеком. */
export function Drafts({ drafts, onConfirmed }: { drafts: any[]; onConfirmed?: () => void }) {
  const [status, setStatus] = useState<Record<string, string>>({});
  const q = useQueryClient();
  async function confirm(d: any) {
    setStatus((v) => ({ ...v, [d.id]: "Обработка…" }));
    try {
      const r = await api("/under/drafts/" + d.id + "/confirm", { method: "POST", body: "{}" });
      setStatus((v) => ({ ...v, [d.id]: "Создана заявка " + r.code }));
      q.invalidateQueries({ queryKey: ["bootstrap"] });
      onConfirmed?.();
    } catch (e: any) {
      setStatus((v) => ({ ...v, [d.id]: e.message }));
    }
  }
  return (
    <>
      {drafts.map((d) => {
        const ok = status[d.id]?.startsWith("Создана");
        return (
          <div className={"uh-draft " + (ok ? "ok" : "")} key={d.id}>
            <span className="eyebrow">{ok ? "ЗАЯВКА СОЗДАНА" : "ТРЕБУЕТ ПОДТВЕРЖДЕНИЯ"}</span>
            <h3>{d.payload.title}</h3>
            <p>
              {d.vehicle_code} · {d.payload.description}
            </p>
            <small>{ok ? "Обращение сохранено в вашей сессии." : "Черновик действует 10 минут. Заявка ещё не создана."}</small>
            <button
              className="button primary"
              disabled={status[d.id] === "Обработка…" || ok || !navigator.onLine}
              onClick={() => confirm(d)}
            >
              <CheckCircle2 size={16} />
              Подтвердить создание заявки
            </button>
            {status[d.id] && <p role="status">{status[d.id]}</p>}
          </div>
        );
      })}
    </>
  );
}
