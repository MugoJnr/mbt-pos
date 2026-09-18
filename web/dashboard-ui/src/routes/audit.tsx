import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, ShieldCheck } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Card, Input, PageHeader, Table } from "@/components/ui-kit";
import { GET } from "@/lib/api";

export const Route = createFileRoute("/audit")({
  component: AuditLog,
});

function AuditLog() {
  const [q, setQ] = useState("");
  const logsQ = useQuery({
    queryKey: ["audit-log"],
    queryFn: () => GET<any[]>("/audit"),
  });
  const rows = Array.isArray(logsQ.data) ? logsQ.data : [];
  const shown = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return rows;
    return rows.filter((row: any) =>
      [row.action, row.module, row.username, row.user_name, row.details, row.created_at]
        .some((value) => String(value || "").toLowerCase().includes(term)),
    );
  }, [rows, q]);
  return (
    <AppShell title="Audit Log">
      <PageHeader
        eyebrow="Admin"
        title="Audit Log"
        icon={<ShieldCheck className="h-4 w-4" />}
        description="Immutable activity history for sales, debt, stock, users, settings and security actions."
        actions={
          <div className="relative min-w-[260px]">
            <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-text2" />
            <Input className="pl-8" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search activity…" />
          </div>
        }
      />
      <Card className="overflow-hidden">
        {logsQ.isLoading ? (
          <div className="py-12 text-center text-sm text-text2">Loading audit history…</div>
        ) : (
          <Table head={["When", "User", "Action", "Module", "Details"]}>
            {shown.map((row: any) => (
              <tr key={row.id}>
                <td className="whitespace-nowrap px-4 py-2.5 text-xs text-text2">
                  {String(row.created_at || "").slice(0, 19)}
                </td>
                <td className="px-4 py-2.5 text-text">{row.username || row.user_name || "System"}</td>
                <td className="px-4 py-2.5"><Badge tone="info">{row.action || "ACTION"}</Badge></td>
                <td className="px-4 py-2.5 text-text2">{row.module || "—"}</td>
                <td className="max-w-xl px-4 py-2.5 text-sm text-text2">{row.details || "—"}</td>
              </tr>
            ))}
          </Table>
        )}
        {!logsQ.isLoading && !shown.length ? (
          <div className="py-12 text-center text-sm text-text2">No matching activity.</div>
        ) : null}
      </Card>
    </AppShell>
  );
}
