import { Drafts } from "./under/Drafts";
import { useState, lazy, Suspense } from "react";
import { useQuery } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Legend,
} from "recharts";
import {
  ArrowUpRight,
  ArrowRight,
  CarFront,
  Clock3,
  Wrench,
  Wallet,
  TrendingUp,
  AlertCircle,
  CalendarDays,
  MapPin,
  Plus,
  FileText,
  Download,
  CheckCircle2,
  X,
  Send,
  Sparkles,
  LoaderCircle,
  Upload,
  ShieldCheck,
  ExternalLink,
  RefreshCw,
  Smartphone,
  Users,
  ArrowDownLeft,
  ChevronRight,
  Building2,
  Filter,
  Grid2X2,
  List,
  Gift,
  TriangleAlert,
} from "lucide-react";
import {
  api,
  Data,
  Row,
  dirs,
  statuses,
  kinds,
  rub,
  num,
  dt,
  getLabel,
  availableActions,
  financialRoles,
} from "./lib";
import { Badge, Table, Card, CarPhoto, Empty, Loading } from "./ui";
// Leaflet (~45 КБ gzip) нужен только карте площадок — грузим его отдельно
const BranchMap = lazy(() => import("./branchmap").then((m) => ({ default: m.BranchMap })));
type Props = {
  data: Data;
  open: (r: Row) => void;
  act: (id: string, label: string, target?: Row) => void;
  search: string;
  branch: string;
  direction: string;
};
function filtered(rows: Row[], p: Props) {
  return rows.filter(
    (r) =>
      (!p.direction ||
        r.direction === p.direction ||
        p.data.vehicle.find((v) => v.id === r.vehicle)?.direction ===
          p.direction) &&
      (!p.branch ||
        r.branch === p.branch ||
        p.data.vehicle.find((v) => v.id === r.vehicle)?.branch === p.branch) &&
      (!p.search ||
        JSON.stringify(r).toLowerCase().includes(p.search.toLowerCase()) ||
        getLabel(p.data, r.client)
          .toLowerCase()
          .includes(p.search.toLowerCase()) ||
        getLabel(p.data, r.vehicle)
          .toLowerCase()
          .includes(p.search.toLowerCase())),
  );
}
export function Dashboard(p: Props & { report: any; go: (s: string) => void }) {
  const r = p.report;
  if (!r) return <Loading />;
  const tickets = filtered(p.data.ticket, p).filter(
    (t) => t.status !== "closed",
  );
  const chart = r.daily.map((d: any) => ({
    ...d,
    revenue: Number(d.revenue),
    payments: Number(d.payments),
  }));
  return (
    <>
      <div className="kpi-grid">
        <KPI
          label="Начисленная выручка"
          value={rub(r.revenue)}
          note="По договорам за выбранный период"
          icon={<Wallet />}
        />
        <KPI
          label="Результат парка"
          value={rub(r.profit)}
          note="После прямых и общих расходов"
          icon={<TrendingUp />}
        />
        <KPI
          label="Загрузка сейчас"
          value={`${r.utilization}%`}
          note={`${r.active} из ${r.fleet} автомобилей в работе`}
          icon={<CarFront />}
        />
        <KPI
          label="Дебиторская задолженность"
          value={rub(r.debt)}
          note="Начислено, но ещё не оплачено"
          icon={<Clock3 />}
          warning
        />
      </div>
      <div className="dashboard-top">
        <Card className="revenue-chart">
          <div className="card-head">
            <div>
              <span className="eyebrow">ЭКОНОМИКА ПАРКА</span>
              <h2>Выручка и поступления</h2>
            </div>
            <span className="subtle-chip">
              {dt(r.start)} — {dt(r.end)}
            </span>
          </div>
          <div className="chart-legend">
            <span>
              <i style={{ background: "var(--chart-1)" }} />
              Начислено <strong>{rub(r.revenue)}</strong>
            </span>
            <span>
              <i style={{ background: "var(--chart-2)" }} />
              Получено <strong>{rub(r.payments)}</strong>
            </span>
          </div>
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height="100%" minHeight={225}>
              <AreaChart
                data={chart}
                margin={{ top: 15, right: 8, bottom: 0, left: 0 }}
              >
                <defs>
                  <linearGradient id="revenueFill" x1="0" y1="0" x2="0" y2="1">
                    <stop
                      offset="0%"
                      style={{ stopColor: "var(--chart-1)", stopOpacity: 0.4 }}
                    />
                    <stop
                      offset="95%"
                      style={{ stopColor: "var(--chart-1)", stopOpacity: 0.02 }}
                    />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 5" vertical={false} />
                <XAxis
                  dataKey="date"
                  tickFormatter={dt}
                  axisLine={false}
                  tickLine={false}
                  minTickGap={38}
                  fontSize={10}
                />
                <YAxis
                  tickFormatter={(v) => `${Math.round(v / 1000)}к`}
                  axisLine={false}
                  tickLine={false}
                  width={43}
                  fontSize={10}
                />
                <Tooltip
                  formatter={(v: any) => rub(v)}
                  labelFormatter={(v) => dt(String(v))}
                  wrapperStyle={{ outline: "none" }}
                />
                <Area
                  className="area-1"
                  name="Начислено"
                  dataKey="revenue"
                  type="monotone"
                  strokeWidth={2}
                  fill="url(#revenueFill)"
                />
                <Area
                  className="area-2"
                  name="Получено"
                  dataKey="payments"
                  type="monotone"
                  fill="transparent"
                  strokeWidth={2}
                  strokeDasharray="4 4"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <section className="fleet-focus">
          <div className="focus-top">
            <span>АВТОПАРК СЕГОДНЯ</span>
            <CarFront size={20} />
          </div>
          <div className="focus-count">
            {r.fleet}
            <span>
              автомобилей
              <br />
              под контролем
            </span>
          </div>
          <div className="focus-photos">
            {[
              "/cars/exeed-lx-sm.webp",
              "/cars/moskvich-3-sm.webp",
              "/cars/haval-f7-sm.webp",
            ].map((src) => (
              <img key={src} src={src} alt="" loading="lazy" />
            ))}
          </div>
          <div className="focus-status">
            <div>
              <i className="green" />
              <strong>{r.active}</strong>
              <span>В работе</span>
            </div>
            <div>
              <i className="yellow" />
              <strong>{r.ready}</strong>
              <span>Доступны</span>
            </div>
            <div>
              <i className="orange" />
              <strong>{r.repair}</strong>
              <span>Ремонт</span>
            </div>
          </div>
          <button onClick={() => p.go("fleet")}>
            Открыть автопарк <ArrowUpRight size={16} />
          </button>
        </section>
      </div>
      <div className="section-heading">
        <div>
          <span className="eyebrow">ОПЕРАЦИОННЫЙ КОНТРОЛЬ</span>
          <h2>
            Требует вашего внимания{" "}
            <span className="count-bubble">{tickets.length}</span>
          </h2>
        </div>
        <button className="text-button" onClick={() => p.go("service")}>
          Все обращения <ArrowRight size={16} />
        </button>
      </div>
      <div className="attention-grid">
        {tickets.slice(0, 3).map((t, i) => (
          <button
            className="attention-card"
            key={t.id}
            onClick={() => p.open(t)}
          >
            <div className="attention-header">
              <span
                className={
                  "task-icon " + (t.priority === "urgent" ? "red" : "")
                }
              >
                <Wrench size={17} />
              </span>
              <Badge value={t.status} />
              <ArrowUpRight size={17} />
            </div>
            <h3>{t.title}</h3>
            <p>{getLabel(p.data, t.vehicle)}</p>
            {t.scheduled_at && (
              <p>
                Сервис:{" "}
                {new Date(t.scheduled_at).toLocaleString("ru-RU", {
                  timeZone: "Europe/Moscow",
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}{" "}
                МСК
              </p>
            )}
            <div className="attention-bottom">
              <span>
                <Clock3 size={13} />{" "}
                {new Date(t.due) < new Date()
                  ? "Срок реакции истёк"
                  : `До ${new Date(t.due).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`}
              </span>
              <strong>
                {Number(t.estimate) ? rub(t.estimate) : "Нужен осмотр"}
              </strong>
            </div>
          </button>
        ))}
      </div>
      <div className="dashboard-bottom">
        <Card>
          <div className="card-head">
            <div>
              <span className="eyebrow">ПО АВТОМОБИЛЯМ</span>
              <h2>Результат в деталях</h2>
            </div>
            <button className="text-button" onClick={() => p.go("analytics")}>
              Вся аналитика <ArrowUpRight size={16} />
            </button>
          </div>
          <Table
            rows={r.rows.slice(0, 5)}
            columns={[
              {
                accessorKey: "model",
                header: "Автомобиль",
                cell: ({ row }: any) => (
                  <div className="cell-title">
                    <strong>{row.original.model}</strong>
                    <small>{row.original.code}</small>
                  </div>
                ),
              },
              {
                accessorKey: "revenue",
                header: "Начислено",
                cell: ({ getValue }: any) => rub(getValue()),
              },
              {
                accessorKey: "expenses",
                header: "Расходы",
                cell: ({ getValue }: any) => rub(getValue()),
              },
              {
                accessorKey: "result",
                header: "Результат",
                cell: ({ getValue }: any) => (
                  <strong
                    className={
                      Number(getValue()) >= 0 ? "positive" : "negative"
                    }
                  >
                    {rub(getValue())}
                  </strong>
                ),
              },
            ]}
            onSelect={(r) => {
              const v = p.data.vehicle.find((v) => v.id === r.id);
              if (v) p.open(v);
            }}
          />
        </Card>
        <Card className="branches">
          <div className="card-head">
            <div>
              <span className="eyebrow">ПЛОЩАДКИ</span>
              <h2>Вся Москва рядом</h2>
            </div>
            <MapPin size={18} />
          </div>
          <Suspense fallback={<div className="branch-leaflet" />}>
          <BranchMap
            branches={p.data.branches}
            counts={Object.fromEntries(
              p.data.branches.map((b) => [
                b.id,
                p.data.vehicle.filter((v) => v.branch === b.id).length,
              ]),
            )}
          />
          </Suspense>
          {p.data.branches.map((b) => (
            <div className="branch-row" key={b.id}>
              <span className="tiny-dot" />
              <div>
                <strong>{b.name}</strong>
                <small>{b.address}</small>
              </div>
              <b>{p.data.vehicle.filter((v) => v.branch === b.id).length}</b>
            </div>
          ))}
        </Card>
      </div>
    </>
  );
}
function KPI({
  label,
  value,
  note,
  icon,
  warning = false,
}: {
  label: string;
  value: string;
  note: string;
  icon: React.ReactNode;
  warning?: boolean;
}) {
  return (
    <Card className={"kpi " + (warning ? "kpi-warning" : "")}>
      <div className="kpi-label">
        {label}
        <span>{icon}</span>
      </div>
      <strong>{value}</strong>
      <small>
        {warning ? (
          <span className="tiny-dot orange" />
        ) : (
          <span className="tiny-dot" />
        )}
        {note}
      </small>
    </Card>
  );
}
export function Fleet(p: Props) {
  const [mode, setMode] = useState("table");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState(p.data.today);
  const [to, setTo] = useState(
    new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10),
  );
  const [freeOnly, setFreeOnly] = useState(false);
  const availability = useQuery({
    queryKey: ["availability", from, to, p.data.session.role],
    queryFn: () => api(`/availability?start=${from}&end=${to}`),
    enabled: to > from,
  });
  const rows = filtered(p.data.vehicle, p).filter(
    (v) =>
      (!status || v.status === status) &&
      (!freeOnly ||
        availability.data?.items.some(
          (a: any) => a.id === v.id && a.available,
        )),
  );
  return (
    <>
      <div className="availability-bar">
        <div>
          <strong>Календарь доступности</strong>
          <small>Брони, резервы и техническая готовность</small>
        </div>
        <label>
          С
          <input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
        </label>
        <label>
          По
          <input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={freeOnly}
            onChange={(e) => setFreeOnly(e.target.checked)}
          />
          Только свободные
        </label>
        <strong>
          {availability.data?.items.filter((a: any) => a.available).length ??
            "—"}{" "}
          доступны
        </strong>
      </div>
      {availability.error && (
        <div className="error">{availability.error.message}</div>
      )}
      <div className="list-toolbar">
        <div className="tabs">
          {[
            ["", "Все автомобили"],
            ["ready", "Готовы"],
            ["repair", "Ремонт"],
            ["inspection", "Осмотр"],
          ].map(([id, label]) => (
            <button
              className={status === id ? "active" : ""}
              key={id}
              onClick={() => setStatus(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="view-toggle">
          <button
            aria-label="Таблица"
            className={mode === "table" ? "selected" : ""}
            onClick={() => setMode("table")}
          >
            <List size={16} />
          </button>
          <button
            aria-label="Карточки"
            className={mode === "cards" ? "selected" : ""}
            onClick={() => setMode("cards")}
          >
            <Grid2X2 size={16} />
          </button>
        </div>
      </div>
      {mode === "table" ? (
        <Card>
          <Table
            rows={rows}
            columns={[
              {
                accessorKey: "model",
                header: "Автомобиль",
                cell: ({ row }) => (
                  <div className="vehicle-cell">
                    <CarPhoto v={row.original} size="xs" />
                    <div className="cell-title">
                      <strong>{row.original.model}</strong>
                      <small>
                        {row.original.code} · {row.original.year}
                      </small>
                    </div>
                  </div>
                ),
              },
              {
                accessorKey: "direction",
                header: "Направление",
                cell: ({ getValue }) => (
                  <span className="subtle-chip">{dirs[getValue()]}</span>
                ),
              },
              {
                accessorKey: "branch",
                header: "Площадка",
                cell: ({ getValue }) =>
                  p.data.branches.find((b) => b.id === getValue())?.name,
              },
              {
                accessorKey: "status",
                header: "Готовность",
                cell: ({ getValue }) => <Badge value={getValue()} />,
              },
              {
                accessorKey: "mileage",
                header: "Пробег",
                cell: ({ getValue }) => num(getValue()) + " км",
              },
              {
                accessorKey: "rate",
                header: "Ставка / сутки",
                cell: ({ getValue }) => <strong>{rub(getValue())}</strong>,
              },
            ]}
            onSelect={p.open}
          />
        </Card>
      ) : (
        <div className="vehicle-grid">
          {rows.slice(0, 60).map((v) => (
            <button
              className="vehicle-card card"
              key={v.id}
              onClick={() => p.open(v)}
            >
              <div className="vehicle-card-head">
                <Badge value={v.status} />
                <span>{v.code}</span>
              </div>
              <CarPhoto v={v} />
              <h3>{v.model}</h3>
              <div className="muted">
                {v.year} · {num(v.mileage)} км · {dirs[v.direction]}
              </div>
              <div className="vehicle-card-bottom">
                <strong>
                  {rub(v.rate)} <small>/ сутки</small>
                </strong>
                <ArrowUpRight size={20} />
              </div>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
export function People(p: Props) {
  const [tab, setTab] = useState("clients");
  return (
    <>
      <div className="tabs standalone">
        {[
          ["clients", "Клиенты и водители"],
          ["owners", "Владельцы автомобилей"],
          ["referrals", "Реферальная программа"],
        ].map(([id, label]) => (
          <button
            className={tab === id ? "active" : ""}
            key={id}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <Card>
        {tab === "clients" ? (
          <Table
            rows={p.data.client.filter(
              (c) =>
                !p.search ||
                c.name.toLowerCase().includes(p.search.toLowerCase()),
            )}
            columns={[
              {
                accessorKey: "name",
                header: "Участник",
                cell: ({ row }) => (
                  <div className="person-cell">
                    <div className="avatar">
                      {row.original.name.slice(0, 2).toUpperCase()}
                    </div>
                    <div className="cell-title">
                      <strong>{row.original.name}</strong>
                      <small>{row.original.code}</small>
                    </div>
                  </div>
                ),
              },
              {
                accessorKey: "type",
                header: "Тип",
                cell: ({ getValue }) =>
                  getValue() === "company" ? "Организация" : "Физическое лицо",
              },
              { accessorKey: "phone", header: "Телефон" },
              {
                accessorKey: "status",
                header: "Проверка",
                cell: ({ getValue }) => <Badge value={getValue()} />,
              },
              {
                accessorKey: "documents",
                header: "Документы",
                cell: ({ getValue }) =>
                  `${getValue()?.length || 0} в комплекте`,
              },
            ]}
            onSelect={p.open}
          />
        ) : tab === "owners" ? (
          <>
            <div className="card-head">
              <h2>Сторонние владельцы</h2>
              <span className="subtle-chip">24 автомобиля в управлении</span>
            </div>
            <Table
              rows={p.data.investor}
              columns={[
                { accessorKey: "name", header: "Владелец" },
                {
                  accessorKey: "share",
                  header: "Доля дохода",
                  cell: ({ getValue }) => `${Number(getValue()) * 100}%`,
                },
                {
                  accessorKey: "expense_share",
                  header: "Доля расходов",
                  cell: ({ getValue }) => `${Number(getValue()) * 100}%`,
                },
                {
                  id: "cars",
                  header: "Автомобилей",
                  cell: ({ row }) =>
                    p.data.vehicle.filter((v) => v.investor === row.original.id)
                      .length,
                },
              ]}
              onSelect={p.open}
            />
          </>
        ) : (
          <>
            <div className="card-head">
              <h2>Приглашения и бонусы</h2>
              <button
                className="button secondary"
                onClick={() => p.act("referral.create", "Новое приглашение")}
              >
                <Plus size={15} />
                Приглашение
              </button>
            </div>
            <Table
              rows={p.data.referral}
              columns={[
                {
                  id: "client",
                  header: "Пригласил",
                  cell: ({ row }) => getLabel(p.data, row.original.client),
                },
                {
                  id: "invited",
                  header: "Приглашён",
                  cell: ({ row }) => getLabel(p.data, row.original.invited),
                },
                {
                  accessorKey: "amount",
                  header: "Бонус",
                  cell: ({ getValue }) => rub(getValue()),
                },
                {
                  accessorKey: "status",
                  header: "Статус",
                  cell: ({ getValue }) => <Badge value={getValue()} />,
                },
              ]}
              onSelect={p.open}
            />
          </>
        )}
      </Card>
    </>
  );
}
export function Contracts(p: Props) {
  const [status, setStatus] = useState("");
  return (
    <>
      <div className="tabs standalone">
        {[
          ["", "Все договоры"],
          ["active", "Действующие"],
          ["draft", "Черновики"],
          ["confirmed", "К выдаче"],
          ["completed", "Завершённые"],
        ].map(([id, label]) => (
          <button
            className={status === id ? "active" : ""}
            key={id}
            onClick={() => setStatus(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <Card>
        <Table
          rows={filtered(p.data.contract, p).filter(
            (c) => !status || c.status === status,
          )}
          columns={[
            {
              accessorKey: "code",
              header: "Договор",
              cell: ({ row }) => (
                <div className="cell-title">
                  <strong>{row.original.code}</strong>
                  <small>{dirs[row.original.direction]}</small>
                </div>
              ),
            },
            {
              id: "client",
              header: "Клиент",
              cell: ({ row }) => getLabel(p.data, row.original.client),
            },
            {
              id: "vehicle",
              header: "Автомобиль",
              cell: ({ row }) => getLabel(p.data, row.original.vehicle),
            },
            {
              accessorKey: "end",
              header: "Период",
              cell: ({ row }) =>
                `${dt(row.original.start)} — ${dt(row.original.end)}`,
            },
            {
              accessorKey: "rate",
              header: "Ставка",
              cell: ({ getValue }) => rub(getValue()),
            },
            {
              accessorKey: "status",
              header: "Статус",
              cell: ({ getValue }) => <Badge value={getValue()} />,
            },
          ]}
          onSelect={p.open}
        />
      </Card>
    </>
  );
}
export function Service(p: Props) {
  const [only, setOnly] = useState("all");
  const rows = filtered(p.data.ticket, p)
    .filter((t) => only !== "overdue" || new Date(t.due) < new Date())
    .filter((t) => only !== "open" || t.status !== "closed")
    .filter(
      (t) => only !== "scheduled" || (t.scheduled_at && t.status !== "closed"),
    );
  return (
    <>
      <div className="list-toolbar">
        <div className="tabs">
          {[
            ["all", "Все заявки"],
            ["open", "В работе"],
            ["overdue", "Просрочено"],
            ["scheduled", "Запись в сервис"],
          ].map(([id, label]) => (
            <button
              className={only === id ? "active" : ""}
              key={id}
              onClick={() => setOnly(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="muted">{rows.length} обращений</span>
      </div>
      <div className="kanban">
        {[
          ["new", "Новые"],
          ["estimate", "Согласование"],
          ["approved", "Готовы к ремонту"],
          ["repair", "В ремонте"],
          ["quality", "Контроль"],
          ["closed", "Завершены"],
        ].map(([status, label]) => (
          <div className="kanban-column" key={status}>
            <div className="kanban-heading">
              <span>{label}</span>
              <b>{rows.filter((t) => t.status === status).length}</b>
            </div>
            {rows
              .filter((t) => t.status === status)
              .map((t) => (
                <button
                  className="kanban-card"
                  key={t.id}
                  onClick={() => p.open(t)}
                >
                  <div className="kanban-card-top">
                    <small>{t.code}</small>
                    <Badge value={t.priority} />
                  </div>
                  <h3>{t.title}</h3>
                  <p>{getLabel(p.data, t.vehicle)}</p>
                  {t.scheduled_at && (
                    <p>
                      Сервис:{" "}
                      {new Date(t.scheduled_at).toLocaleString("ru-RU", {
                        timeZone: "Europe/Moscow",
                        day: "numeric",
                        month: "short",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}{" "}
                      МСК
                    </p>
                  )}
                  <div className="kanban-meta">
                    <span>
                      <Clock3 size={12} />
                      {dt(t.due)}
                    </span>
                    <strong>{rub(t.estimate)}</strong>
                  </div>
                  <div className="kanban-assignee">
                    <div className="avatar tiny">ТО</div>
                    {t.assignee}
                  </div>
                </button>
              ))}
            {!rows.some((t) => t.status === status) && (
              <div className="kanban-empty">Пока нет заявок</div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
export function Finance(p: Props & { report: any; done: (m: string) => void }) {
  const [tab, setTab] = useState("ledger");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const canWrite = ["owner", "admin", "finance"].includes(p.data.session.role);
  const ledger = useQuery({
    queryKey: [
      "ledger",
      p.data.session.role,
      offset,
      p.report?.start,
      p.report?.end,
    ],
    queryFn: () =>
      api(
        "/ledger?offset=" +
          offset +
          "&start=" +
          p.report.start +
          "&end=" +
          p.report.end,
      ),
    enabled: !!p.report,
  });
  async function upload(f?: File) {
    if (!f) return;
    setLoading(true);
    setErr("");
    try {
      const form = new FormData();
      form.append("file", f);
      const file = await api("/files", { method: "POST", body: form });
      const preview = await api("/import/preview", {
        method: "POST",
        body: JSON.stringify({ file: file.id }),
      });
      p.done("Выписка подготовлена к сверке");
      p.open({ ...preview, kind: "import" });
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }
  const r = p.report;
  return (
    <>
      {r && (
        <div className="kpi-grid three">
          <KPI
            label="Деньги получены"
            value={rub(r.payments)}
            note="Арендные поступления за период"
            icon={<ArrowDownLeft />}
          />
          <KPI
            label="Задолженность"
            value={rub(r.debt)}
            note="Неоплаченные начисления"
            icon={<Clock3 />}
            warning
          />
          <KPI
            label="Залоги за период"
            value={rub(r.deposits)}
            note="Отдельно от выручки"
            icon={<ShieldCheck />}
          />
        </div>
      )}
      <div className="list-toolbar">
        <div className="tabs">
          {[
            ["ledger", "Операции"],
            ["imports", "Сверка выписок"],
            ["owners", "Расчёты с владельцами"],
          ]
            .filter(
              ([id]) =>
                canWrite ||
                id === "ledger" ||
                (id === "owners" && p.data.session.role === "investor"),
            )
            .map(([id, label]) => (
              <button
                className={tab === id ? "active" : ""}
                key={id}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
        </div>
        {canWrite && (
          <div className="inline-buttons">
            <button
              className="button secondary"
              onClick={() => p.act("period.close", "Закрыть месяц")}
            >
              Закрыть месяц
            </button>
            <button
              className="button primary"
              onClick={() => p.act("payment.create", "Зачислить оплату")}
            >
              <Plus size={15} />
              Платёж
            </button>
          </div>
        )}
      </div>
      {tab === "ledger" && (
        <Card>
          <Table
            rows={(ledger.data?.rows || []).filter(
              (e: any) =>
                !p.search ||
                JSON.stringify(e)
                  .toLowerCase()
                  .includes(p.search.toLowerCase()),
            )}
            columns={[
              {
                accessorKey: "date",
                header: "Дата",
                cell: ({ getValue }) => dt(getValue()),
              },
              {
                accessorKey: "kind",
                header: "Операция",
                cell: ({ getValue }) => (
                  <span className={"ledger-type " + getValue()}>
                    {kinds[getValue()] || getValue()}
                  </span>
                ),
              },
              { accessorKey: "reason", header: "Основание" },
              {
                id: "vehicle",
                header: "Автомобиль",
                cell: ({ row }) => getLabel(p.data, row.original.vehicle),
              },
              {
                accessorKey: "amount",
                header: "Сумма",
                cell: ({ row }) => (
                  <strong
                    className={
                      row.original.kind === "payment" ? "positive" : ""
                    }
                  >
                    {rub(row.original.amount)}
                  </strong>
                ),
              },
              {
                id: "action",
                header: "",
                cell: ({ row }) =>
                  canWrite ? (
                    <button
                      className="text-button"
                      onClick={() =>
                        p.act(
                          "entry.reverse",
                          "Сторнировать операцию",
                          row.original,
                        )
                      }
                    >
                      Сторно
                    </button>
                  ) : null,
              },
            ]}
            pageSize={20}
          />
          <div className="table-footer">
            <span>В журнале {num(ledger.data?.total)} операций</span>
            <div className="inline-buttons">
              <button
                disabled={!offset}
                className="button secondary small"
                onClick={() => setOffset(Math.max(0, offset - 200))}
              >
                Предыдущие 200
              </button>
              <button
                disabled={offset + 200 >= (ledger.data?.total || 0)}
                className="button secondary small"
                onClick={() => setOffset(offset + 200)}
              >
                Следующие 200
              </button>
            </div>
          </div>
        </Card>
      )}
      {tab === "imports" && (
        <>
          <Card className="import-box">
            <div className="task-icon">
              <Upload size={22} />
            </div>
            <h2>Выписка → проверка → зачисление</h2>
            <p>
              CSV или XLSX с колонками reference, contract, date, amount.
              <br />
              Повторы отсеиваются, неизвестные договоры остаются на сверке.
            </p>
            <div className="inline-buttons">
              <label className="button primary">
                {loading ? "Обрабатываем…" : "Загрузить выписку"}
                <input
                  hidden
                  type="file"
                  accept=".csv,.xlsx"
                  disabled={loading}
                  onChange={(e) => upload(e.target.files?.[0])}
                />
              </label>
              <a className="button secondary" href="/api/v1/import/sample">
                <Download size={15} />
                Скачать пример
              </a>
            </div>
            {err && <div className="error">{err}</div>}
          </Card>
          <Card>
            <Table
              rows={p.data.import}
              columns={[
                { accessorKey: "name", header: "Файл" },
                { accessorKey: "posted", header: "Зачислено" },
                {
                  accessorKey: "status",
                  header: "Статус",
                  cell: ({ getValue }) => <Badge value={getValue()} />,
                },
                {
                  id: "unmatched",
                  header: "На сверке",
                  cell: ({ row }) => row.original.unmatched?.length || 0,
                },
              ]}
              onSelect={p.open}
            />
          </Card>
        </>
      )}
      {tab === "owners" && (
        <Card>
          <div className="card-head">
            <h2>Месячные отчёты владельцев</h2>
            {canWrite && (
              <button
                className="button primary"
                onClick={() => p.act("owner.statement", "Сформировать отчёт")}
              >
                <Plus size={16} />
                Новый отчёт
              </button>
            )}
          </div>
          <Table
            rows={p.data.statement}
            columns={[
              { accessorKey: "month", header: "Месяц" },
              {
                id: "investor",
                header: "Владелец",
                cell: ({ row }) => getLabel(p.data, row.original.investor),
              },
              {
                accessorKey: "amount",
                header: "К выплате",
                cell: ({ getValue }) => rub(getValue()),
              },
              {
                accessorKey: "status",
                header: "Статус",
                cell: ({ getValue }) => <Badge value={getValue()} />,
              },
            ]}
            onSelect={p.open}
          />
        </Card>
      )}
    </>
  );
}
export function Analytics(p: Props & { report: any }) {
  const [rate, setRate] = useState(0);
  const [util, setUtil] = useState(0);
  const [cost, setCost] = useState(0);
  const r = p.report;
  if (!r) return <Loading />;
  const forecast =
    Number(r.revenue) * (1 + rate / 100) * (1 + util / 100) -
    Number(r.expenses) * (1 + cost / 100) -
    Number(r.overhead);
  return (
    <>
      <div className="kpi-grid three">
        <KPI
          label="Начисленная выручка"
          value={rub(r.revenue)}
          note="В выбранном периоде"
          icon={<Wallet />}
        />
        <KPI
          label="Прямые расходы"
          value={rub(r.expenses)}
          note="Связаны с автомобилями"
          icon={<Wrench />}
        />
        <KPI
          label="Результат после общих расходов"
          value={rub(r.profit)}
          note="Методика расчёта раскрыта ниже"
          icon={<TrendingUp />}
        />
      </div>
      <div className="analytics-grid">
        <Card>
          <div className="card-head">
            <h2>Доходность по направлениям</h2>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={Object.entries(dirs).map(([id, name]) => ({
                name,
                revenue: r.rows
                  .filter((v: any) => v.direction === id)
                  .reduce((a: number, v: any) => a + Number(v.revenue), 0),
                result: r.rows
                  .filter((v: any) => v.direction === id)
                  .reduce((a: number, v: any) => a + Number(v.result), 0),
              }))}
            >
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="name"
                fontSize={11}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                tickFormatter={(v) => rub(v, true)}
                width={70}
                fontSize={10}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip formatter={(v: any) => rub(v)} />
              <Legend />
              <Bar
                className="bar-1"
                dataKey="revenue"
                name="Выручка"
                fill="#f5c400"
                radius={[5, 5, 0, 0]}
              />
              <Bar
                className="bar-2"
                dataKey="result"
                name="Результат"
                fill="#2aa7f0"
                radius={[5, 5, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card className="scenario">
          <span className="eyebrow">СЦЕНАРНЫЙ РАСЧЁТ</span>
          <h2>Что изменит результат?</h2>
          {[
            ["Ставка аренды", rate, setRate],
            ["Оплачиваемые дни", util, setUtil],
            ["Прямые расходы", cost, setCost],
          ].map(([label, value, set]: any) => (
            <label className="slider" key={label}>
              <span>
                {label}
                <strong>
                  {value > 0 ? "+" : ""}
                  {value}%
                </strong>
              </span>
              <input
                type="range"
                min="-30"
                max="30"
                value={value}
                onChange={(e) => set(Number(e.target.value))}
              />
            </label>
          ))}
          <div className="scenario-result">
            <small>Результат при заданных допущениях</small>
            <strong>{rub(forecast)}</strong>
            <span
              className={forecast >= Number(r.profit) ? "positive" : "negative"}
            >
              {rub(forecast - Number(r.profit))} к фактическому
            </span>
          </div>
          <small className="muted">
            Сценарий не изменяет договоры и проведённые операции.
          </small>
        </Card>
      </div>
      <Card>
        <div className="card-head">
          <h2>Экономика каждого автомобиля</h2>
          <span className="subtle-chip">{r.rows.length} автомобилей</span>
        </div>
        <Table
          rows={r.rows.filter(
            (v: any) =>
              !p.search ||
              JSON.stringify(v).toLowerCase().includes(p.search.toLowerCase()),
          )}
          columns={[
            {
              accessorKey: "model",
              header: "Автомобиль",
              cell: ({ row }) => (
                <div className="cell-title">
                  <strong>{row.original.model}</strong>
                  <small>{row.original.code}</small>
                </div>
              ),
            },
            {
              accessorKey: "revenue",
              header: "Начислено",
              cell: ({ getValue }) => rub(getValue()),
            },
            {
              accessorKey: "payments",
              header: "Получено",
              cell: ({ getValue }) => rub(getValue()),
            },
            {
              accessorKey: "expenses",
              header: "Расходы",
              cell: ({ getValue }) => rub(getValue()),
            },
            {
              accessorKey: "overhead",
              header: "Общие",
              cell: ({ getValue }) => rub(getValue()),
            },
            {
              accessorKey: "result",
              header: "Результат",
              cell: ({ getValue }) => (
                <strong
                  className={Number(getValue()) >= 0 ? "positive" : "negative"}
                >
                  {rub(getValue())}
                </strong>
              ),
            },
          ]}
          onSelect={(r) => {
            const v = p.data.vehicle.find((v) => v.id === r.id);
            if (v) p.open(v);
          }}
        />
      </Card>
      <div className="notice">
        Прогноз упущенной выручки за дни ремонта:{" "}
        <strong>
          {rub(
            r.rows.reduce(
              (sum: number, v: any) =>
                sum + Number(v.lost_revenue_estimate || 0),
              0,
            ),
          )}
        </strong>
        . Текущая базовая ставка × зафиксированные дни простоя; это оценка
        потенциала, она не входит в фактический результат.
      </div>
      <div className="methodology">
        <ShieldCheck size={18} />
        <p>{r.methodology}</p>
      </div>
    </>
  );
}
export function SettingsPage(p: Props & { done: (s: string) => void }) {
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api("/settings"),
  });
  const [reset, setReset] = useState(false);
  return (
    <>
      <div className="integration-grid">
        {[
          {
            name: "Telegram",
            status: p.data.telegram_username
              ? "Подключён"
              : "Ожидается отдельный бот",
            mode: "Реальный канал",
            icon: <Send />,
          },
          {
            name: "AI-провайдер",
            status: p.data.ai_configured ? "Ключ настроен" : "Не настроен",
            mode: "Реальные вызовы · $0.50 / сутки",
            icon: <Sparkles />,
          },
          {
            name: "Учётная система",
            status: "Файловый импорт",
            mode: "Тестовый адаптер",
            icon: <Building2 />,
          },
          {
            name: "Банковские поступления",
            status: "CSV / XLSX · сверка",
            mode: "Тестовый источник",
            icon: <Wallet />,
          },
        ].map((x) => (
          <Card key={x.name} className="integration">
            <div className="task-icon">{x.icon}</div>
            <h3>{x.name}</h3>
            <strong>{x.status}</strong>
            <small>{x.mode}</small>
          </Card>
        ))}
      </div>
      <Card>
        <div className="card-head">
          <div>
            <span className="eyebrow">
              ПОДТВЕРЖДЁННЫЕ СВЕДЕНИЯ И УЧЕБНЫЕ ПРАВИЛА
            </span>
            <h2>Источники бизнес-логики</h2>
          </div>
        </div>
        <div className="sources">
          {p.data.sources.map((s, i) => (
            <div key={i}>
              <div className="source-number">
                {String(i + 1).padStart(2, "0")}
              </div>
              <div>
                <h3>{s.title}</h3>
                <p>{s.text}</p>
                <small>
                  Версия {s.version} ·{" "}
                  {s.url
                    ? "Публичная информация компании"
                    : "Демонстрационное допущение"}
                </small>
              </div>
              {s.url && (
                <a
                  href={s.url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={"Открыть " + s.title}
                >
                  <ExternalLink size={18} />
                </a>
              )}
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <div className="card-head">
          <h2>Тарифы и версии</h2>
          <button
            className="button secondary"
            onClick={() => p.act("tariff.create", "Новая версия тарифа")}
          >
            <Plus size={16} />
            Добавить
          </button>
        </div>
        <Table
          rows={p.data.tariff}
          columns={[
            { accessorKey: "name", header: "Название" },
            {
              accessorKey: "direction",
              header: "Направление",
              cell: ({ getValue }) => dirs[getValue()],
            },
            {
              accessorKey: "rate",
              header: "Ставка",
              cell: ({ getValue }) => rub(getValue()),
            },
            {
              accessorKey: "effective",
              header: "Действует с",
              cell: ({ getValue }) => dt(getValue()),
            },
            { accessorKey: "version", header: "Версия" },
          ]}
        />
      </Card>
      <div className="analytics-grid">
        <Card className="settings-card">
          <h2>AI: качество и расход</h2>
          <p>
            Сумма запросов этой сессии:{" "}
            <strong>
              $
              {settings.data?.usage
                .reduce((a: number, u: any) => a + Number(u.cost), 0)
                .toFixed(4) || "0.0000"}
            </strong>
          </p>
          <p>
            Общий лимит приложения: $0.50 в сутки МСК. Расходы остальных
            приложений не входят.
          </p>
          {settings.data?.quality?.models?.length ? (
            <div className="quality-list">
              <small>
                Прогон {settings.data.quality.suite} ·{" "}
                {dt(settings.data.quality.tested_at)}
              </small>
              {settings.data.quality.models.map((m: any) => (
                <div key={m.model} className="quality-row">
                  <strong>
                    {m.model}
                    {m.model === settings.data.quality.selected && (
                      <span className="subtle-chip">основная</span>
                    )}
                  </strong>
                  <span>
                    {m.passed} из {m.cases} · точность{" "}
                    {Math.round(m.accuracy * 100)}% · медиана{" "}
                    {(m.median_ms / 1000).toFixed(1)} с · прогон $
                    {Number(m.cost).toFixed(3)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">
              Отчёт проверки качества появится после измерений.
            </p>
          )}
          <a
            className="text-button"
            href="/api/docs"
            target="_blank"
            rel="noreferrer"
          >
            Документация API <ArrowUpRight size={16} />
          </a>
        </Card>
        <Card className="settings-card">
          <h2>Ваше пространство</h2>
          <p>
            Учебные данные изолированы от других посетителей. Сессия доступна 24
            часа после последнего действия.
          </p>
          <p>
            Закрытые месяцы: {settings.data?.closed_months.join(", ") || "нет"}
          </p>
          <div className="inline-buttons">
            <button
              className="button secondary"
              onClick={() => p.act("period.reopen", "Переоткрыть месяц")}
            >
              Переоткрыть месяц
            </button>
            <button className="button secondary" onClick={() => setReset(true)}>
              <RefreshCw size={15} />
              Сбросить демо
            </button>
          </div>
          {reset && (
            <div className="error">
              Будут удалены только данные вашей демосессии.
              <div className="inline-buttons">
                <button
                  className="button secondary"
                  onClick={() => setReset(false)}
                >
                  Отмена
                </button>
                <button
                  className="button primary"
                  onClick={async () => {
                    try {
                      await api("/session/reset", {
                        method: "POST",
                        body: "{}",
                      });
                      location.reload();
                    } catch (e: any) {
                      p.done(e.message);
                    }
                  }}
                >
                  Подтвердить сброс
                </button>
              </div>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
export function MobileHome(p: Props & { report: any; onTelegram: () => void }) {
  const role = p.data.session.role;
  const contracts = p.data.contract.filter((c) => c.status === "active");
  const vehicle =
    p.data.vehicle.find((v) => v.id === contracts[0]?.vehicle) ||
    p.data.vehicle[0];
  return (
    <>
      <div className="mobile-home-grid">
        <section className="mobile-car">
          <span className="eyebrow">
            {role === "investor" ? "АВТОМОБИЛИ В УПРАВЛЕНИИ" : "ВАШ АВТОМОБИЛЬ"}
          </span>
          <h2>{vehicle?.model || "Выберите автомобиль"}</h2>
          <p>
            {vehicle?.code} · {vehicle?.year}
          </p>
          <CarPhoto v={vehicle} size="lg" />
          {vehicle && (
            <button className="button primary" onClick={() => p.open(vehicle)}>
              Открыть карточку <ArrowUpRight size={17} />
            </button>
          )}
        </section>
        <Card className="mobile-balance">
          <span className="eyebrow">РАСЧЁТЫ</span>
          <h2>
            {role === "investor"
              ? "Экономика ваших автомобилей"
              : "Прозрачный баланс"}
          </h2>
          <div className="balance-row">
            <span>Начислено за период</span>
            <strong>{rub(p.report?.revenue)}</strong>
          </div>
          <div className="balance-row">
            <span>Получено платежей</span>
            <strong className="positive">{rub(p.report?.payments)}</strong>
          </div>
          <div className="balance-row">
            <span>Задолженность</span>
            <strong>{rub(p.report?.debt)}</strong>
          </div>
          <button className="button secondary" onClick={p.onTelegram}>
            <Send size={16} />
            Подключить Telegram
          </button>
        </Card>
      </div>
      <div className="quick-actions">
        <button
          onClick={() => p.act("ticket.create", "Создать обращение", vehicle)}
        >
          <Wrench />
          <strong>Нужна помощь</strong>
          <span>Ремонт, ТО, вопрос</span>
        </button>
        <button onClick={() => contracts[0] && p.open(contracts[0])}>
          <CalendarDays />
          <strong>Мой договор</strong>
          <span>График и начисления</span>
        </button>
        <button
          onClick={() => p.act("contract.create", "Подобрать автомобиль")}
        >
          <CarFront />
          <strong>Выбрать автомобиль</strong>
          <span>Аренда и выкуп</span>
        </button>
      </div>
      <Card>
        <div className="card-head">
          <h2>
            {role === "investor" ? "Сметы на согласование" : "Мои обращения"}
          </h2>
        </div>
        <Table
          rows={p.data.ticket}
          columns={[
            { accessorKey: "title", header: "Обращение" },
            {
              accessorKey: "status",
              header: "Статус",
              cell: ({ getValue }) => <Badge value={getValue()} />,
            },
            {
              accessorKey: "estimate",
              header: "Смета",
              cell: ({ getValue }) => rub(getValue()),
            },
          ]}
          onSelect={p.open}
        />
      </Card>
      {role === "investor" && (
        <Card>
          <div className="card-head">
            <h2>Отчёты и выплаты</h2>
          </div>
          <Table
            rows={p.data.statement}
            columns={[
              { accessorKey: "month", header: "Месяц" },
              {
                accessorKey: "amount",
                header: "Сумма",
                cell: ({ getValue }) => rub(getValue()),
              },
              {
                accessorKey: "status",
                header: "Статус",
                cell: ({ getValue }) => <Badge value={getValue()} />,
              },
            ]}
            onSelect={p.open}
          />
        </Card>
      )}
    </>
  );
}
export function DetailPanel(p: Props & { row: Row; onClose: () => void }) {
  const detail = useQuery<Row>({
    queryKey: ["detail", p.row.id, p.data.session.role],
    queryFn: () => api("/items/" + p.row.id),
  });
  const x = detail.data || p.row;
  const [tab, setTab] = useState("overview");
  const actions = availableActions(x, p.data.session.role);
  const labels: Record<string, string> = {
    direction: "Направление",
    branch: "Площадка",
    client: "Клиент",
    vehicle: "Автомобиль",
    investor: "Владелец",
    start: "Начало",
    end: "Окончание",
    schedule: "График",
    rate: "Ставка / сутки",
    deposit: "Залог",
    mileage: "Пробег",
    next_to: "Следующее ТО",
    document_until: "Документы до",
    fuel: "Топливо, %",
    final_payment: "Выкупной платёж",
    payer: "Плательщик",
    estimate: "Согласованная смета",
    actual: "Фактическая стоимость",
    due: "Срок реакции",
    amount: "Сумма",
    month: "Месяц",
    phone: "Телефон",
    type: "Тип клиента",
    age: "Возраст",
    experience: "Стаж",
    share: "Доля дохода",
    expense_share: "Доля расходов",
    basis: "База расчёта",
    work: "Состав работ",
    description: "Описание",
    additional_driver: "Дополнительный водитель",
    services_amount: "Разовые услуги, ₽",
    addons_rule: "Условия дополнительных услуг",
    initial_fuel: "Топливо при выдаче, %",
    review_reason: "Решение проверки",
    close_quote: "Досрочный выкуп",
    request_reason: "Заявление",
    scheduled_at: "Запись в сервис",
    terms_reason: "Основание условий выкупа",
    substitution_for: "Подмена по договору",
  };
  const fmt = (k: string, v: any) =>
    [
      "rate",
      "deposit",
      "final_payment",
      "estimate",
      "actual",
      "amount",
      "close_quote",
    ].includes(k)
      ? rub(v)
      : ["vehicle", "client", "investor", "substitution_for"].includes(k)
        ? getLabel(p.data, v)
        : k === "scheduled_at"
          ? new Date(v).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" }) +
            " МСК"
          : k === "branch"
            ? p.data.branches.find((b) => b.id === v)?.name
            : k === "direction"
              ? dirs[v]
              : ["start", "end", "due", "document_until"].includes(k)
                ? dt(v)
                : ["mileage", "next_to"].includes(k)
                  ? num(v) + " км"
                  : statuses[v] || String(v ?? "—");
  return (
    <Dialog.Root open onOpenChange={(o) => !o && p.onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="drawer-overlay" />
        <Dialog.Content
          className="drawer"
          // клик по плавающей кнопке AI не закрывает карточку: помощник открывается поверх с её контекстом
          onPointerDownOutside={(e) => {
            if ((e.target as HTMLElement)?.closest?.(".ask-fab")) e.preventDefault();
          }}
          onInteractOutside={(e) => {
            if ((e.target as HTMLElement)?.closest?.(".ask-fab")) e.preventDefault();
          }}
        >
          <div className="drawer-top">
            <div>
              <span className="eyebrow">
                {x.code} · ВЕРСИЯ {x.version}
              </span>
              <Dialog.Title>
                {x.model ||
                  x.name ||
                  x.title ||
                  (x.kind === "contract"
                    ? "Договор " + x.code
                    : x.kind === "statement"
                      ? "Отчёт владельца"
                      : "Детали операции")}
              </Dialog.Title>
            </div>
            <Dialog.Close className="icon-button" aria-label="Закрыть карточку">
              <X />
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">
            Детали объекта, доступные действия и история изменений
          </Dialog.Description>
          {x.status && <Badge value={x.status} />}
          <div className="tabs standalone">
            <button
              className={tab === "overview" ? "active" : ""}
              onClick={() => setTab("overview")}
            >
              Обзор
            </button>
            {x.calendar && (
              <button
                className={tab === "calendar" ? "active" : ""}
                onClick={() => setTab("calendar")}
              >
                Начисления
              </button>
            )}
            {x.allocation && (
              <button
                className={tab === "allocation" ? "active" : ""}
                onClick={() => setTab("allocation")}
              >
                Погашение
              </button>
            )}
            {x.ledger && (
              <button
                className={tab === "finance" ? "active" : ""}
                onClick={() => setTab("finance")}
              >
                Операции
              </button>
            )}
            <button
              className={tab === "history" ? "active" : ""}
              onClick={() => setTab("history")}
            >
              История
            </button>
          </div>
          {detail.error && <div className="error">{detail.error.message}</div>}
          {tab === "overview" && (
            <>
              {x.kind === "vehicle" && (
                <div className="drawer-car">
                  <CarPhoto v={x} size="lg" />
                </div>
              )}
              <dl className="facts">
                {Object.entries(labels)
                  .filter(([k]) => x[k] !== undefined && x[k] !== null)
                  .map(([k, label]) => (
                    <div key={k}>
                      <dt>{label}</dt>
                      <dd>{fmt(k, x[k])}</dd>
                    </div>
                  ))}
              </dl>
              {x.documents && (
                <div className="document-chips">
                  {x.documents.map((d: string) => (
                    <span key={d}>
                      <FileText size={13} />
                      {d}
                    </span>
                  ))}
                </div>
              )}
                {x.document_files?.length > 0 && <div className="document-chips">{x.document_files.map((doc: any) => <a key={doc.file} href={`/api/v1/files/${doc.file}`} target="_blank" rel="noreferrer"><FileText size={14} />{doc.type === "passport" ? "Паспорт" : "Водительское удостоверение"} · {doc.name}</a>)}</div>}
                {x.refund_status === "pending" && <p className="muted">Запрос возврата залога: {rub(x.refund_requested)} · ожидает финансиста</p>}
              {x.photos?.length > 0 && (
                <div className="document-chips">
                  {x.photos.map((id: string, i: number) => (
                    <a
                      href={"/api/v1/files/" + id}
                      key={id}
                      className="button secondary small"
                    >
                      Фото {i + 1}
                      <Download size={13} />
                    </a>
                  ))}
                </div>
              )}
              {x.holiday_request?.length > 0 && (
                <div className="notice">
                  Запрошены каникулы: {x.holiday_request.join(", ")}
                </div>
              )}
              {x.schedule_request && (
                <div className="notice">
                  Запрошен график: {x.schedule_request}
                </div>
              )}
              {x.terms_approved === false && (
                <div className="notice">
                  Предложение выкупа ожидает утверждения финансистом
                </div>
              )}
              {x.substitute_contract && (
                <button
                  className="button secondary"
                  onClick={() => {
                    const c = p.data.contract.find(
                      (v) => v.id === x.substitute_contract,
                    );
                    if (c) p.open(c);
                  }}
                >
                  Открыть договор подмены
                </button>
              )}
              {x.close_requested && (
                <div className="notice">
                  Клиент запросил расчёт досрочного выкупа
                </div>
              )}
              {x.contracts?.length > 0 && (
                <div className="related">
                  <h3>Связанные договоры</h3>
                  {x.contracts.map((c: Row) => (
                    <button key={c.id} onClick={() => p.open(c)}>
                      <FileText size={16} />
                      {c.code}
                      <Badge value={c.status} />
                      <ChevronRight size={15} />
                    </button>
                  ))}
                </div>
              )}
              {x.tickets?.length > 0 && (
                <div className="related">
                  <h3>Обращения</h3>
                  {x.tickets.map((t: Row) => (
                    <button key={t.id} onClick={() => p.open(t)}>
                      <Wrench size={16} />
                      {t.title}
                      <ChevronRight size={15} />
                    </button>
                  ))}
                </div>
              )}
              {x.lines && (
                <div className="statement-lines">
                  {x.lines.map((line: any) => (
                    <div key={line.vehicle}>
                      <strong>{line.model}</strong>
                      <span>Поступления: {rub(line.income)}</span>
                      <span>Расходы: {rub(line.expenses)}</span>
                      <b>Владельцу: {rub(line.amount)}</b>
                    </div>
                  ))}
                </div>
              )}
              {x.kind === "import" && (
                <div className="import-preview">
                  <h3>Строки выписки</h3>
                  {(x.unmatched?.length ? x.unmatched : x.rows || []).map(
                    (r: any, i: number) => (
                      <div key={i}>
                        <strong>
                          {r.reference} · {rub(r.amount)}
                        </strong>
                        <span>
                          {r.contract} · {r.date}
                        </span>
                        {r.error && (
                          <small className="negative">{r.error}</small>
                        )}
                      </div>
                    ),
                  )}
                </div>
              )}
            </>
          )}
          {tab === "calendar" && (
            <div className="calendar-list">
              {(x.calendar || []).map((d: any, i: number) => (
                <div className={Number(d.amount) ? "" : "free"} key={i}>
                  <span>{dt(d.date)}</span>
                  <small>{d.reason}</small>
                  <strong>{rub(d.amount)}</strong>
                </div>
              ))}
            </div>
          )}
          {tab === "finance" && (
            <div className="calendar-list">
              {(x.ledger || []).map((e: any) => (
                <div key={e.id}>
                  <span>{dt(e.date)}</span>
                  <small>
                    {kinds[e.kind]}
                    <br />
                    {e.reason}
                  </small>
                  <strong className={e.kind === "payment" ? "positive" : ""}>
                    {rub(e.amount)}
                  </strong>
                </div>
              ))}
            </div>
          )}
          {tab === "allocation" && (
            <>
              <div className="notice">
                {x.allocation?.method} Аванс: {rub(x.allocation?.advance)}
              </div>
              <div className="calendar-list">
                {x.allocation?.rows.map((r: any) => (
                  <div key={r.id}>
                    <span>{dt(r.date)}</span>
                    <small>
                      {r.reason}
                      <br />
                      Погашено: {rub(r.covered)} из {rub(r.amount)}
                    </small>
                    <strong>Долг {rub(r.remaining)}</strong>
                  </div>
                ))}
              </div>
            </>
          )}
          {tab === "history" && (
            <div className="timeline">
              {x.events?.length ? (
                x.events.map((e: any) => (
                  <div key={e.id}>
                    <i />
                    <strong>{e.title}</strong>
                    <small>
                      {dt(e.at)} · {p.data.session.roles[e.role] || e.role}
                    </small>
                  </div>
                ))
              ) : (
                <Empty title="Изменений пока нет">
                  Выполните действие — оно появится в истории.
                </Empty>
              )}
            </div>
          )}
          <div className="drawer-actions">
            {actions.map((a) => (
              <button
                key={a.id}
                className="button primary"
                onClick={() => p.act(a.id, a.label, x)}
              >
                {a.label}
                <ArrowUpRight size={15} />
              </button>
            ))}
            {[
              "contract",
              "statement",
              "ticket",
              "vehicle",
              "inspection",
            ].includes(x.kind) && (
              <div className="inline-buttons">
                <a
                  className="button secondary"
                  href={"/api/v1/documents/" + x.id + "?format=pdf"}
                >
                  <Download size={15} />
                  PDF
                </a>
                <a
                  className="button secondary"
                  href={"/api/v1/documents/" + x.id + "?format=xlsx"}
                >
                  <Download size={15} />
                  Excel
                </a>
              </div>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
const FIELD_LABELS: Record<string, string> = {
  title: "Заголовок",
  priority: "Приоритет",
  category: "Категория",
  missing: "Уточнить",
  number: "Номер",
  date: "Дата",
  amount: "Сумма",
  issuer: "Кем выдан",
};
/** Ответ модели: абзацы и маркированные строки, ссылки «(ист. N)» — компактными метками. */
export function AnswerText({ text }: { text: string }) {
  const blocks = String(text || "")
    .split(/\n{2,}/)
    .map((b) => b.trim())
    .filter(Boolean);
  const cite = (line: string) =>
    line.split(/(\(ист\.?\s*[\d,\s]+\))/g).map((part, i) =>
      /^\(ист/.test(part) ? (
        <span className="cite" key={i}>
          {part.replace(/[()]/g, "").replace("ист.", "ист ")}
        </span>
      ) : (
        part
      ),
    );
  return (
    <div className="ai-answer">
      {blocks.map((b, i) => {
        const lines = b.split(/\n/).map((l) => l.trim());
        if (lines.length > 1 && lines.every((l) => /^[•\-–]\s/.test(l)))
          return (
            <ul key={i}>
              {lines.map((l, j) => (
                <li key={j}>{cite(l.replace(/^[•\-–]\s/, ""))}</li>
              ))}
            </ul>
          );
        return <p key={i}>{cite(b)}</p>;
      })}
    </div>
  );
}
export function AIPanel({
  data,
  target,
  onClose,
  container,
}: {
  data: Data;
  target: Row | null;
  onClose: () => void;
  /** куда монтировать панель: в консоли «Под капотом» — в тёмный контейнер */
  container?: HTMLElement | null;
}) {
  const [prompt, setPrompt] = useState("");
  const [mode, setMode] = useState("agent");
  const [job, setJob] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [file, setFile] = useState<string | null>(null);
  const result = useQuery({
    queryKey: ["ai", job],
    queryFn: () => api("/jobs/" + job),
    enabled: !!job,
    refetchInterval: (query) =>
      ["done", "failed"].includes((query.state.data as any)?.state)
        ? false
        : 1500,
  });
  async function send() {
    setPending(true);
    setError("");
    try {
      const r = await api("/ai", {
        method: "POST",
        body: JSON.stringify({ prompt, mode, target: target?.id, file }),
      });
      setJob(r.id);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setPending(false);
    }
  }
  async function upload(f?: File) {
    if (!f) return;
    setPending(true);
    try {
      const form = new FormData();
      form.append("file", f);
      const r = await api("/files", { method: "POST", body: form });
      setFile(r.id);
      setMode("document");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setPending(false);
    }
  }
  const busy =
    pending || (!!job && !["done", "failed"].includes(result.data?.state));
  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal container={container ?? undefined}>
        <Dialog.Overlay className="drawer-overlay" />
        <Dialog.Content className="drawer ai-drawer">
          <div className="drawer-top">
            <div>
              <span className="eyebrow">AI · РЕАЛЬНЫЕ ДАННЫЕ ВАШЕЙ СЕССИИ</span>
              <Dialog.Title>
                <Sparkles size={22} /> Помощник парка
              </Dialog.Title>
            </div>
            <Dialog.Close
              className="icon-button"
              aria-label="Закрыть помощника"
            >
              <X />
            </Dialog.Close>
          </div>
          <Dialog.Description className="muted">
            Объясняет цифры, находит правила и готовит черновики. Финансовые
            решения подтверждает сотрудник.
          </Dialog.Description>
          <details className="ai-guard">
            <summary>
              <TriangleAlert size={15} />
              <span>
                <b>Демо-стенд: guardrails-слой не подключён</b>
                <small>Ответы модели выводятся без пост-фильтрации</small>
              </span>
            </summary>
            <p>
              Права роли применяются на уровне данных: инструменты агента
              возвращают только объекты, доступные роли, а запись идёт через
              черновик с подтверждением. Но сам текст ответа LLM в демо не
              проходит защитные прослойки, поэтому в формулировках могут
              оказаться сведения, лишние для этой роли.
            </p>
            <p>В промышленной версии между моделью и пользователем стоят:</p>
            <ul>
              <li>
                <b>Input / output guardrails</b> — модерация запроса и ответа,
                защита от prompt injection и jailbreak
              </li>
              <li>
                <b>Policy enforcement</b> — проверка ответа по политике
                раскрытия для роли (что можно сообщать клиенту, водителю,
                сотруднику)
              </li>
              <li>
                <b>PII redaction / DLP</b> — маскирование персональных и
                коммерческих данных (152-ФЗ) до отправки в модель и в ответе
              </li>
              <li>
                <b>Output validation</b> — проверка структуры и фактов ответа
                по данным инструментов (LLM-as-judge / правила), аудит
                отклонённых ответов
              </li>
            </ul>
          </details>
          <div className="ai-modes">
            {[
              ["agent", "Агент"],
              ["knowledge", "Регламенты"],
              ["ticket", "Обращение"],
              ["finance", "Экономика"],
              ["document", "Документ"],
            ].map(([id, label]) => (
              <button
                className={mode === id ? "selected" : ""}
                onClick={() => setMode(id)}
                key={id}
              >
                {label}
              </button>
            ))}
          </div>
          {target && (
            <div className="notice">
              Контекст: {target.code} ·{" "}
              {target.model || target.title || "Выбранная запись"}
            </div>
          )}
          <div className="ai-suggestions">
            {[
              "Какие документы нужны водителю?",
              "Кто оплачивает ремонт?",
              "Как рассчитывается выплата владельцу?",
            ].map((t) => (
              <button onClick={() => setPrompt(t)} key={t}>
                {t}
                <ArrowUpRight size={13} />
              </button>
            ))}
          </div>
          <label className="ai-input">
            Ваш вопрос
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Например: почему изменился результат автомобиля?"
              rows={5}
            />
          </label>
          {mode === "document" && (
            <label className="upload">
              <Upload size={16} />
              {file ? "Документ прикреплён" : "Прикрепить PDF или изображение"}
              <input
                type="file"
                accept=".pdf,.png,.jpg,.jpeg"
                onChange={(e) => upload(e.target.files?.[0])}
              />
            </label>
          )}
          <button
            className="button primary"
            disabled={busy || prompt.length < 2}
            onClick={send}
          >
            {busy ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <Send size={16} />
            )}{" "}
            {busy ? "Анализируем…" : "Отправить"}
          </button>
          {error && <div className="error">{error}</div>}
          {result.error && <div className="error">{result.error.message}</div>}
          {result.data?.state === "failed" && (
            <div className="error">{result.data.result.error}</div>
          )}
          {result.data?.state === "done" && (
            <div className="ai-result">
              <div className="ai-result-title">
                <Sparkles size={16} />
                <strong>Результат</strong>
              </div>
              <AnswerText text={result.data.result.answer} />
              <Drafts drafts={result.data.result.drafts || []} />
              {result.data.result.fields &&
                Object.keys(result.data.result.fields).length > 0 && (
                  <dl className="facts">
                    {Object.entries(result.data.result.fields).map(([k, v]) => (
                      <div key={k}>
                        <dt>{FIELD_LABELS[k] || k}</dt>
                        <dd>
                          {Array.isArray(v)
                            ? v.join(", ") || "—"
                            : typeof v === "object" && v
                              ? JSON.stringify(v)
                              : statuses[String(v)] ||
                                String(v ?? "Не указано")}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
              {result.data.result.sources?.length > 0 && (
                <div className="ai-sources-title">Источники</div>
              )}
              {result.data.result.sources?.map((s: any, i: number) => (
                <div className="ai-source" key={i}>
                  <span className="ai-source-num">{i + 1}</span>
                  <div>
                    <strong>{s.title}</strong>
                    <small>
                      Версия {s.version}
                      {s.url && (
                        <>
                          {" · "}
                          <a href={s.url} target="_blank" rel="noreferrer">
                            открыть источник ↗
                          </a>
                        </>
                      )}
                    </small>
                  </div>
                </div>
              ))}
              <div className="ai-meta">
                {result.data.result.model} · {result.data.result.tokens} токенов
                · ${Number(result.data.result.cost).toFixed(5)}
              </div>
            </div>
          )}
          <div className="ai-footnote">
            <ShieldCheck size={16} />
            <span>
              Данные ограничены ролью на уровне инструментов. Текст ответа в
              демо не фильтруется — см. «guardrails-слой» выше.
            </span>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
