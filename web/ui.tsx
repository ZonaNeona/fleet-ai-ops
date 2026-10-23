import { useState, ReactNode } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  ColumnDef,
  SortingState,
} from "@tanstack/react-table";
import {
  ArrowUpDown,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Search,
  Inbox,
  LoaderCircle,
  Moon,
  Sun,
} from "lucide-react";
import { Row, statuses } from "./lib";
export function Badge({ value }: { value: string }) {
  return <span className={"badge " + value}>{statuses[value] || value}</span>;
}
export function Empty({
  title = "Здесь пока ничего нет",
  children,
}: {
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <Inbox size={32} />
      <h3>{title}</h3>
      <p>{children || "Измените фильтры или создайте первую запись."}</p>
    </div>
  );
}
export function Loading() {
  return (
    <div className="empty">
      <LoaderCircle className="spin" />
      <p>Собираем данные вашего парка…</p>
    </div>
  );
}
export function Table({
  rows,
  columns,
  onSelect,
  pageSize = 12,
}: {
  rows: Row[];
  columns: ColumnDef<Row, any>[];
  onSelect?: (r: Row) => void;
  pageSize?: number;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [page, setPage] = useState(0);
  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  const safePage = Math.min(page, Math.max(0, Math.ceil(rows.length / pageSize) - 1));
  const display = table.getRowModel().rows.slice(safePage * pageSize, (safePage + 1) * pageSize);
  if (!rows.length) return <Empty />;
  return (
    <>
      <div className="table-scroll">
        <table>
          <thead>
            {table.getHeaderGroups().map((g) => (
              <tr key={g.id}>
                {g.headers.map((h) => (
                  <th key={h.id}>
                    <button className="sort" onClick={h.column.getToggleSortingHandler()}>
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {h.column.getCanSort() && <ArrowUpDown size={11} />}
                    </button>
                  </th>
                ))}
                {onSelect && <th />}
              </tr>
            ))}
          </thead>
          <tbody>
            {display.map((r) => (
              <tr key={r.id}>
                {r.getVisibleCells().map((c) => (
                  <td key={c.id}>{flexRender(c.column.columnDef.cell, c.getContext())}</td>
                ))}
                {onSelect && (
                  <td>
                    <button
                      className="icon-button"
                      aria-label={"Открыть " + (r.original.code || r.original.id)}
                      onClick={() => onSelect(r.original)}
                    >
                      <ArrowUpRight size={17} />
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-footer">
        <span>
          {safePage * pageSize + 1}–{Math.min((safePage + 1) * pageSize, rows.length)} из {rows.length}
        </span>
        <div>
          <button
            className="icon-button"
            aria-label="Предыдущая страница"
            disabled={safePage === 0}
            onClick={() => setPage(safePage - 1)}
          >
            <ChevronLeft size={16} />
          </button>
          <button
            className="icon-button"
            aria-label="Следующая страница"
            disabled={(safePage + 1) * pageSize >= rows.length}
            onClick={() => setPage(safePage + 1)}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </>
  );
}
export function SearchBox({
  value,
  onChange,
  placeholder = "Поиск по парку…",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="search">
      <Search size={16} />
      <input
        aria-label={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
      {value && (
        <button onClick={() => onChange("")} aria-label="Очистить поиск">
          ×
        </button>
      )}
    </div>
  );
}
export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={"card " + className}>{children}</section>;
}
// Фото модели: из данных автомобиля (image/thumb), иначе — по названию модели (сессии, созданные до обновления парка)
const MODEL_PHOTO: [RegExp, string][] = [
  [/rapid/i, "skoda-rapid"], [/polo/i, "vw-polo"], [/москвич/i, "moskvich-3"], [/emgrand/i, "geely-emgrand"],
  [/tiggo/i, "chery-tiggo-4"], [/belgee/i, "belgee-x50"], [/jolion/i, "haval-jolion"], [/haval/i, "haval-f7"],
  [/sonata/i, "hyundai-sonata"], [/exeed/i, "exeed-lx"], [/preface/i, "geely-preface"], [/hongqi/i, "hongqi-h5"],
  [/mercedes/i, "mercedes-e"], [/bmw/i, "bmw-xm"], [/zeekr/i, "zeekr-9x"], [/largus/i, "lada-largus"],
  [/atlant/i, "sollers-atlant"], [/argo/i, "sollers-argo"], [/газель|gazel/i, "gazelle-next"],
];
export function carPhoto(v: Record<string, any> | undefined, small = false) {
  if (v?.image?.endsWith(".webp")) return small ? v.thumb || v.image : v.image;
  const slug = MODEL_PHOTO.find(([re]) => re.test(v?.model || ""))?.[1] || "haval-f7";
  return `/cars/${slug}${small ? "-sm" : ""}.webp`;
}
export function CarPhoto({
  v,
  size = "md",
  className = "",
}: {
  v: Record<string, any> | undefined;
  size?: "xs" | "md" | "lg";
  className?: string;
}) {
  return (
    <div className={`car-photo ${size} ${className}`}>
      <img src={carPhoto(v, size !== "lg")} alt={v?.model || "Автомобиль"} loading="lazy" decoding="async" />
    </div>
  );
}

/** Светлая/тёмная тема: data-theme на <html>, выбор помним в localStorage (если доступен). */
export function ThemeToggle() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || "light");
  const flip = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", next === "dark" ? "#0a0c0f" : "#f4f5f7");
    try {
      localStorage.setItem("ec-theme", next);
    } catch {
      /* приватный режим — тема просто не запомнится */
    }
    setTheme(next);
  };
  const label = theme === "dark" ? "Светлая тема" : "Тёмная тема";
  return (
    <button className="theme-toggle" onClick={flip} aria-label={label} title={label}>
      {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
    </button>
  );
}
