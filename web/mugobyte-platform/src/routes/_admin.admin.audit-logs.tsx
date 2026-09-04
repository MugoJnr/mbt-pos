import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ScrollText, RefreshCw, Download, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { getAdminOverview } from "@/lib/api";

export const Route = createFileRoute("/_admin/admin/audit-logs")({
  component: AuditLogsPage,
  head: () => ({ meta: [{ title: "Audit Logs | MugoByte" }] }),
});

type AuditLog = {
  id: number | string;
  user_id?: number | string;
  username?: string;
  action: string;
  module?: string;
  details?: string;
  ip_address?: string;
  created_at: string;
};

const MODULE_COLORS: Record<string, string> = {
  auth: "default",
  admin: "destructive",
  settings: "secondary",
  data: "outline",
  system: "secondary",
  security: "destructive",
  license: "secondary",
};

function AuditLogsPage() {
  const [q, setQ] = useState("");
  const [exporting, setExporting] = useState(false);

  const overviewQ = useQuery({
    queryKey: ["admin-overview"],
    queryFn: getAdminOverview,
    refetchInterval: 60_000,
  });

  const cloudAudit = (overviewQ.data?.audit_logs || []).map((r: any) => ({
    id: `cloud-${r.id}`,
    username: String(r.user_id || "system"),
    action: String(r.action || "SECURITY"),
    module: String(r.module || "security"),
    details: typeof r.details === "string" ? r.details : JSON.stringify(r.details || r.meta || {}),
    created_at: String(r.created_at || ""),
  }));
  const licenseHist = (overviewQ.data?.license_history || []).map((r: any) => ({
    id: `lic-${r.id}`,
    username: "license",
    action: String(r.action || "license").toUpperCase(),
    module: "license",
    details: `${r.license_key || ""} ${typeof r.details === "object" ? JSON.stringify(r.details) : (r.details || "")}`.trim(),
    created_at: String(r.created_at || ""),
  }));

  const logs: AuditLog[] = [...cloudAudit, ...licenseHist].sort((a, b) =>
    String(b.created_at).localeCompare(String(a.created_at)),
  );

  const filtered = q
    ? logs.filter((l) =>
        (l.action || "").toLowerCase().includes(q.toLowerCase()) ||
        (l.username || "").toLowerCase().includes(q.toLowerCase()) ||
        (l.module || "").toLowerCase().includes(q.toLowerCase()) ||
        (l.details || "").toLowerCase().includes(q.toLowerCase()),
      )
    : logs;

  async function doExport() {
    try {
      setExporting(true);
      const csv = [
        "created_at,user,action,module,details,ip_address",
        ...filtered.map((row) =>
          [row.created_at, row.username || row.user_id, row.action, row.module, row.details, row.ip_address]
            .map((value) => `"${String(value ?? "").replace(/"/g, '""')}"`)
            .join(","),
        ),
      ].join("\r\n");
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `MugoByte_Audit_Log_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      toast.success("Audit log exported");
    } catch (e: unknown) {
      toast.error((e as Error).message || "Export failed");
    } finally {
      setExporting(false);
    }
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="Admin"
        title="Audit Logs"
        description="Platform-wide cloud audit events and license history (revoke, renew, transfer, privilege changes)."
        actions={
          <>
            <Button variant="outline" onClick={() => overviewQ.refetch()}><RefreshCw className="mr-1.5 h-4 w-4" />Refresh</Button>
            <Button variant="outline" disabled={exporting} onClick={doExport}><Download className="mr-1.5 h-4 w-4" />Export</Button>
          </>
        }
      />

      <div className="mb-4 grid gap-4 sm:grid-cols-3">
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-muted-foreground">Organizations</div><div className="mt-1 font-display text-2xl font-semibold">{overviewQ.data?.organizations.length || 0}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-muted-foreground">Cloud security</div><div className="mt-1 font-display text-2xl font-semibold">{cloudAudit.length}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-muted-foreground">License history</div><div className="mt-1 font-display text-2xl font-semibold">{licenseHist.length}</div></CardContent></Card>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle className="font-display flex items-center gap-2"><ShieldAlert className="h-4 w-4" /> Unified timeline</CardTitle>
              <CardDescription>{logs.length} platform events loaded</CardDescription>
            </div>
            <Input className="h-9 w-64" placeholder="Filter action, user, module…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {overviewQ.isLoading ? (
            <div className="py-12 text-center text-sm text-muted-foreground">Loading audit logs…</div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-16 text-muted-foreground">
              <ScrollText className="h-10 w-10 opacity-30" />
              <p className="text-sm">{q ? "No matching audit events." : "No audit events recorded yet."}</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>User</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Module</TableHead>
                  <TableHead>Details</TableHead>
                  <TableHead>IP</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.slice(0, 500).map((l) => (
                  <TableRow key={String(l.id)}>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{String(l.created_at || "").slice(0, 19).replace("T", " ")}</TableCell>
                    <TableCell className="font-mono text-xs">{l.username || `#${l.user_id}` || "system"}</TableCell>
                    <TableCell className="font-medium">{l.action}</TableCell>
                    <TableCell>
                      <Badge variant={(MODULE_COLORS[l.module || ""] || "outline") as "default" | "secondary" | "destructive" | "outline"}>
                        {l.module || "—"}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-xs truncate text-xs text-muted-foreground">{l.details || "—"}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{l.ip_address || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
