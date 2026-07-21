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
import { GET, listSecurityEvents } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { downloadApi, exportQuery } from "@/lib/download";

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
  const { orgId } = useAuth();
  const [q, setQ] = useState("");
  const [exporting, setExporting] = useState(false);

  const logsQ = useQuery({
    queryKey: ["audit-logs"],
    queryFn: () => GET<AuditLog[]>("/audit"),
    refetchInterval: 60_000,
  });
  const cloudQ = useQuery({
    queryKey: ["cloud-security", orgId],
    queryFn: () => listSecurityEvents(orgId),
    refetchInterval: 60_000,
  });

  const posLogs = Array.isArray(logsQ.data) ? logsQ.data : [];
  const cloudAudit = (cloudQ.data?.audit_logs || []).map((r: any) => ({
    id: `cloud-${r.id}`,
    username: "cloud",
    action: String(r.action || "SECURITY"),
    module: String(r.module || "security"),
    details: typeof r.details === "string" ? r.details : JSON.stringify(r.details || r.meta || {}),
    created_at: String(r.created_at || ""),
  }));
  const licenseHist = (cloudQ.data?.license_history || []).map((r: any) => ({
    id: `lic-${r.id}`,
    username: "license",
    action: String(r.action || "license").toUpperCase(),
    module: "license",
    details: `${r.license_key || ""} ${typeof r.details === "object" ? JSON.stringify(r.details) : (r.details || "")}`.trim(),
    created_at: String(r.created_at || ""),
  }));

  const logs: AuditLog[] = [...cloudAudit, ...licenseHist, ...posLogs].sort((a, b) =>
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
      const qs = exportQuery({ type: "audit", format: "xlsx" });
      await downloadApi(`/reports/export?${qs}`, "MBT_AuditLog.xlsx");
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
        description="POS audit trail plus cloud security events and license history (revoke, renew, transfer, privilege changes)."
        actions={
          <>
            <Button variant="outline" onClick={() => { logsQ.refetch(); cloudQ.refetch(); }}><RefreshCw className="mr-1.5 h-4 w-4" />Refresh</Button>
            <Button variant="outline" disabled={exporting} onClick={doExport}><Download className="mr-1.5 h-4 w-4" />Export</Button>
          </>
        }
      />

      <div className="mb-4 grid gap-4 sm:grid-cols-3">
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-muted-foreground">POS events</div><div className="mt-1 font-display text-2xl font-semibold">{posLogs.length}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-muted-foreground">Cloud security</div><div className="mt-1 font-display text-2xl font-semibold">{cloudAudit.length}</div></CardContent></Card>
        <Card><CardContent className="p-4"><div className="text-xs uppercase text-muted-foreground">License history</div><div className="mt-1 font-display text-2xl font-semibold">{licenseHist.length}</div></CardContent></Card>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle className="font-display flex items-center gap-2"><ShieldAlert className="h-4 w-4" /> Unified timeline</CardTitle>
              <CardDescription>{logs.length} events loaded (cloud + POS)</CardDescription>
            </div>
            <Input className="h-9 w-64" placeholder="Filter action, user, module…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {logsQ.isLoading && cloudQ.isLoading ? (
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
