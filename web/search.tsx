import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Search, X, ArrowUpRight } from "lucide-react";
import { Data, Row, getLabel } from "./lib";
export function GlobalSearch({
  data,
  open,
  onClose,
}: {
  data: Data;
  open: (r: Row) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState("");
  const kinds = ["vehicle", "client", "contract", "ticket", "statement"] as const;
  const labels: Record<string, string> = {
    vehicle: "Автомобиль",
    client: "Клиент",
    contract: "Договор",
    ticket: "Обращение",
    statement: "Отчёт",
  };
  const results = kinds
    .flatMap((k) => data[k])
    .filter(
      (r) =>
        value.trim().length > 1 &&
        [r.code, r.name, r.model, r.title, getLabel(data, r.vehicle), getLabel(data, r.client)]
          .join(" ")
          .toLowerCase()
          .includes(value.toLowerCase()),
    )
    .slice(0, 20);
  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="overlay" />
        <Dialog.Content className="dialog">
          <div className="dialog-top">
            <Dialog.Title>Найти в пространстве</Dialog.Title>
            <Dialog.Close aria-label="Закрыть поиск" className="icon-button">
              <X />
            </Dialog.Close>
          </div>
          <Dialog.Description className="muted">
            Автомобили, люди, договоры и обращения, доступные вашей роли.
          </Dialog.Description>
          <label className="searchbox">
            <Search size={18} />
            <input
              autoFocus
              aria-label="Глобальный поиск"
              placeholder="Модель, код, имя или тема…"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </label>
          <div className="global-results">
            {results.map((r) => (
              <button
                key={r.id}
                onClick={() => {
                  open(r);
                  onClose();
                }}
              >
                <div>
                  <small>
                    {labels[r.kind]} · {r.code}
                  </small>
                  <strong>{r.model || r.name || r.title || getLabel(data, r.vehicle) || r.code}</strong>
                </div>
                <ArrowUpRight size={18} />
              </button>
            ))}
            {value.length > 1 && !results.length && (
              <p className="muted">Ничего не найдено. Попробуйте часть названия или кода.</p>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
