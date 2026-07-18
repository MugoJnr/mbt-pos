import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { HardDrive, Cloud, Play, CheckCircle2, XCircle } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, EmptyState, KpiCard, PageHeader, SectionTitle } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";

export const Route = createFileRoute("/backup")({
  component: BackupPage,
});

function BackupPage() {
  const qc = useQueryClient();
  const statusQ = useQuery({
    queryKey: ["backup-status"],
    queryFn: () => GET<any>("/backup/status"),
    refetchInterval: 30_000,
  });
  const runM = useMutation({
    mutationFn: () => POST("/backup/run", { reason: "manual_web" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["backup-status"] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  const last = statusQ.data?.last;
  const cloud = statusQ.data?.cloud || {};
  const history = Array.isArray(statusQ.data?.history) ? statusQ.data.history : [];

  return (
    <AppShell title="Backup Center">
      <PageHeader
        eyebrow="Command"
        title="Backup Center"
        icon={<HardDrive className="h-4 w-4" />}
        description="Local snapshots and cloud backup status"
        actions={
          <Button
            variant="primary"
            disabled={runM.isPending}
            onClick={() => runM.mutate()}
            className="min-h-[44px]"
          >
            <Play className="h-4 w-4" />
            {runM.isPending ? "Running…" : "Run Backup Now"}
          </Button>
        }
      />

      {runM.data && !(runM.data as any).success ? (
        <Card className="p-3 mb-4 border-err/40 text-sm text-err">
          {(runM.data as any).detail || (runM.data as any).error || "Backup failed"}
        </Card>
      ) : null}
      {runM.isSuccess && (runM.data as any)?.success ? (
        <Card className="p-3 mb-4 border-ok/40 text-sm text-ok">
          {(runM.data as any).detail || "Backup completed"}
        </Card>
      ) : null}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
        <KpiCard
          label="Last Backup"
          value={String(last?.status || "—").toUpperCase()}
          sub={last?.created_at ? String(last.created_at).slice(0, 19) : "Never"}
          accent={last?.status === "ok" ? "ok" : last ? "warn" : "info"}
          icon={<HardDrive className="h-5 w-5" />}
        />
        <KpiCard
          label="Cloud"
          value={cloud.configured ? (cloud.logged_in ? "Ready" : "Sign-in") : "Off"}
          sub={cloud.configured ? "Supabase configured" : "Not configured"}
          accent={cloud.logged_in ? "ok" : cloud.configured ? "warn" : "info"}
          icon={<Cloud className="h-5 w-5" />}
        />
        <KpiCard
          label="Next"
          value="Manual / Desktop"
          sub={statusQ.data?.next_hint || "Schedule via desktop"}
          accent="info"
          icon={<Play className="h-5 w-5" />}
        />
      </div>

      <Card className="overflow-hidden">
        <div className="p-4 border-b border-border">
          <SectionTitle>History</SectionTitle>
        </div>
        {history.length === 0 ? (
          <EmptyState
            title="No backup history"
            description="Trigger a manual backup to create the first snapshot."
          />
        ) : (
          <>
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left border-b border-border bg-panel/40">
                    {["When", "Status", "Reason", "Size", "Detail"].map((h) => (
                      <th
                        key={h}
                        className="px-4 py-2.5 text-[10px] tracking-[0.16em] font-semibold text-text2 uppercase"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {history.map((h: any) => (
                    <tr key={h.id} className="border-b border-border/50">
                      <td className="px-4 py-2.5 font-mono text-xs text-text2">
                        {String(h.created_at || "").slice(0, 19)}
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge tone={h.status === "ok" ? "ok" : h.status === "error" ? "err" : "warn"}>
                          {h.status}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5 text-text2">{h.reason}</td>
                      <td className="px-4 py-2.5 tabular-nums text-text2">
                        {h.size_bytes ? `${(h.size_bytes / 1024).toFixed(1)} KB` : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-text2 truncate max-w-xs">{h.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="md:hidden divide-y divide-border">
              {history.map((h: any) => (
                <div key={h.id} className="p-4">
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="font-mono text-xs text-text2">
                      {String(h.created_at || "").slice(0, 19)}
                    </span>
                    <Badge tone={h.status === "ok" ? "ok" : "err"}>{h.status}</Badge>
                  </div>
                  <div className="text-sm text-text">{h.detail || h.reason}</div>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>

      <div className="mt-3 flex items-center gap-2 text-xs text-text2">
        {cloud.logged_in ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-ok" />
        ) : (
          <XCircle className="h-3.5 w-3.5 text-warn" />
        )}
        Cloud signed-in: {cloud.logged_in ? "yes" : "no"} — local DB copy always available as fallback.
      </div>
    </AppShell>
  );
}
