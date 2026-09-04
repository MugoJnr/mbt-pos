import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudUpload, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getAdminOverview, issueCloudCommand } from "@/lib/api";

export const Route = createFileRoute("/_admin/admin/backups")({
  component: Page,
  head: () => ({ meta: [{ title: "Platform Administration | MugoByte" }] }),
});

function Page() {
  const qc = useQueryClient();
  const overviewQ = useQuery({
    queryKey: ["admin-overview"],
    queryFn: getAdminOverview,
    retry: 1,
  });
  const backupMut = useMutation({
    mutationFn: ({ deviceId, orgId }: { deviceId: string; orgId: string }) =>
      issueCloudCommand(deviceId, "run_backup", {}, orgId),
    onSuccess: (result) => {
      if (result?.error || !result?.ok) {
        toast.error(result?.error || "Backup command failed");
        return;
      }
      toast.success("Backup queued", { description: "The POS will run it on its next command poll." });
      qc.invalidateQueries({ queryKey: ["admin-overview"] });
    },
  });
  const backups = overviewQ.data?.backups || [];
  const devices = overviewQ.data?.devices || [];

  return (
    <PageShell>
      <PageHeader
        eyebrow="Admin"
        title="Backups"
        description="Cloud backup metadata across every registered shop and device."
        actions={
          <Button variant="outline" onClick={() => overviewQ.refetch()} disabled={overviewQ.isFetching}>
            <RefreshCw className={`mr-1.5 h-4 w-4 ${overviewQ.isFetching ? "animate-spin" : ""}`} />Refresh
          </Button>
        }
      />
      {overviewQ.data?.errors?.backups ? (
        <Card className="border-destructive/40">
          <CardContent className="p-4 text-sm text-destructive">{overviewQ.data.errors.backups}</CardContent>
        </Card>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-3">
        <Card><CardContent className="p-5"><div className="text-xs uppercase text-muted-foreground">Backups</div><div className="mt-1 font-display text-2xl font-semibold">{backups.length}</div></CardContent></Card>
        <Card><CardContent className="p-5"><div className="text-xs uppercase text-muted-foreground">Protected shops</div><div className="mt-1 font-display text-2xl font-semibold">{new Set(backups.map((row) => row.business_id).filter(Boolean)).size}</div></CardContent></Card>
        <Card><CardContent className="p-5"><div className="text-xs uppercase text-muted-foreground">Total stored</div><div className="mt-1 font-display text-2xl font-semibold">{(backups.reduce((sum, row) => sum + Number(row.size_bytes || 0), 0) / 1048576).toFixed(1)} MB</div></CardContent></Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="font-display">Recent backups</CardTitle>
          <CardDescription>Newest successful uploads recorded by the cloud backup service.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {overviewQ.isLoading ? <p className="text-sm text-muted-foreground">Loading…</p> : null}
          {!overviewQ.isLoading && backups.length === 0 ? <p className="text-sm text-muted-foreground">No cloud backups have been uploaded.</p> : null}
          {backups.slice(0, 100).map((backup) => (
            <div key={backup.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-border/70 p-4">
              <CloudUpload className="h-5 w-5 text-primary" />
              <div className="min-w-0 flex-1">
                <div className="font-medium">{backup.org_name || backup.business_id || "Unlinked shop"}</div>
                <div className="truncate text-xs text-muted-foreground">{backup.storage_path}</div>
                <div className="text-xs text-muted-foreground">{backup.created_at ? new Date(backup.created_at).toLocaleString() : "Unknown date"} · {((backup.size_bytes || 0) / 1048576).toFixed(1)} MB</div>
              </div>
              <Badge variant="outline">{backup.backup_type || "full_snapshot"}</Badge>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="font-display">Run backup</CardTitle>
          <CardDescription>Queue a backup command for a connected POS device.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {devices.map((device) => (
            <div key={device.id || device.device_id} className="flex flex-wrap items-center gap-3 rounded-xl border border-border/70 p-3">
              <div className="min-w-0 flex-1">
                <div className="font-medium">{device.computer_name || device.hostname || device.device_id}</div>
                <div className="text-xs text-muted-foreground">{device.org_name || device.org_id || "Unlinked organization"}</div>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={!device.device_id || !device.org_id || backupMut.isPending}
                onClick={() => backupMut.mutate({ deviceId: device.device_id!, orgId: device.org_id! })}
              >
                <CloudUpload className="mr-1.5 h-4 w-4" />Backup now
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>
    </PageShell>
  );
}
