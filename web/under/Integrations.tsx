import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, AlertTriangle, Cpu } from "lucide-react";
import { api, Data, Row } from "../lib";
export const sourceNames: Record<string, string> = {
  "1c": "1С · учёт",
  "yandex-pro": "Яндекс Про",
  fines: "Штрафы ГИБДД",
  telematics: "Телематика",
};
export const statusName = (s: string) =>
  ({
    pending: "Ожидает запуска",
    queued: "В очереди",
    running: "Выполняется",
    done: "Завершено",
    failed: "Ошибка",
    success: "Выполнено",
    error: "Ошибка",
  })[s] || s;
export function SourcesWidget({ data, open, go }: { data: Data; open: (r: Row) => void; go?: () => void }) {
  const q = useQuery({
    queryKey: ["integrations", data.session.role],
    queryFn: () => api("/integrations"),
    enabled: ["owner", "admin", "finance", "manager"].includes(data.session.role),
    refetchInterval: 10000,
  });
  if (!q.data) return null;
  return (
    <div className="uh-panel uh-sources-widget">
      <div className="uh-section-head">
        <div>
          <span className="eyebrow">ИСТОЧНИКИ И СВЕРКА</span>
          <h3>Данные приходят из четырёх систем</h3>
        </div>
        {go && (
          <button className="text-button" onClick={go}>
            <Cpu size={14} />
            Как это работает
            <ArrowUpRight size={14} />
          </button>
        )}
      </div>
      <div className="uh-source-grid">
        {q.data.sources.map((s: any) => (
          <div key={s.id}>
            <strong>{sourceNames[s.id]}</strong>
            <span className={"uh-dot " + (s.status === "done" ? "ok" : "")} />
            <small>
              {s.updated
                ? new Date(s.updated).toLocaleString("ru-RU", {
                    timeZone: "Europe/Moscow",
                  })
                : "Ещё не запускался"}
            </small>
            <small>Учебный источник · {statusName(s.status)}</small>
          </div>
        ))}
      </div>
      {q.data.diffs.length > 0 && (
        <details className="uh-reconcile">
          <summary>
            <AlertTriangle size={15} />
            Сверка: {q.data.diffs.length} расхождений
          </summary>
          {q.data.diffs.slice(0, 20).map((d: any) => (
            <button
              key={d.id}
              onClick={() => {
                const v = data.vehicle.find((v) => v.id === d.vehicle);
                if (v) open(v);
              }}
            >
              <span>
                {d.vehicle_code} · {d.field_label}
                <small>
                  В системе: {d.local} · источник: {d.external}
                </small>
              </span>
              <ArrowUpRight size={15} />
            </button>
          ))}
        </details>
      )}
    </div>
  );
}
