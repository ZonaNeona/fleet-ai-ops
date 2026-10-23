import { Data, Row } from "./lib";
import { Card, Table, Badge } from "./ui";
export function Operations({ data, open }: { data: Data; open: (row: Row) => void }) {
  const review = data.client.filter((c) => c.status !== "approved");
  const tickets = data.ticket.filter((t) => t.status !== "closed");
  const issues = data.contract.filter((c) => ["draft", "confirmed"].includes(c.status));
  return (
    <>
      <div className="kpi-grid three">
        {[
          ["Обращения в работе", tickets.length],
          ["Клиенты на проверке", review.length],
          ["Договоры к оформлению", issues.length],
        ].map(([title, count]) => (
          <Card className="kpi" key={title}>
            <span className="kpi-label">{title}</span>
            <strong>{count}</strong>
            <small>В пределах доступа вашей роли</small>
          </Card>
        ))}
      </div>
      {data.session.role !== "screening" && (
        <Card>
          <div className="card-head">
            <h2>Следующее действие</h2>
          </div>
          <Table
            rows={tickets}
            columns={[
              { accessorKey: "code", header: "Заявка" },
              { accessorKey: "title", header: "Обращение" },
              { accessorKey: "status", header: "Этап", cell: ({ getValue }) => <Badge value={getValue()} /> },
              { accessorKey: "assignee", header: "Ответственный" },
            ]}
            onSelect={open}
          />
        </Card>
      )}
      {data.session.role !== "service" && (
        <Card>
          <div className="card-head">
            <h2>Комплектность и проверка</h2>
          </div>
          <Table
            rows={review}
            columns={[
              { accessorKey: "name", header: "Клиент" },
              {
                accessorKey: "status",
                header: "Статус",
                cell: ({ getValue }) => <Badge value={getValue()} />,
              },
              { accessorKey: "documents", header: "Документов", cell: ({ getValue }) => getValue().length },
            ]}
            onSelect={open}
          />
        </Card>
      )}
    </>
  );
}
