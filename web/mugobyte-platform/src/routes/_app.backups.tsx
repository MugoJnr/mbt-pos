import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  CloudUpload, CheckCircle2, AlertTriangle, RefreshCw,
  Calendar, HardDrive, MonitorSmartphone,
} from "lucide-react";
import { toast } from "sonner";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  issueCloudCommand,
  listCloudBackups,
  listCloudDevices,
  type AdminBackup,
  type CloudDevice,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/_app/backups")({
  component: BackupsPage,
  head: () => ({ meta: [{ title: "Backup Center | MugoByte" }] }),
});

function BackupsPage() {
  const { orgId } = useAuth();
  const backupsQ = useQuery({
    queryKey: ["cloud-backups", orgId],
    queryFn: () => listCloudBackups(orgId),
    refetchInterval: 60_000,
  });
  const devicesQ = useQuery({
    queryKey: ["cloud-devices", orgId],
    queryFn: () => listCloudDevices(orgId),
  });

  const runMut = useMutation({
    mutationFn: ({ deviceId }: { deviceId: string }) =>
      issueCloudCommand(deviceId, "run_backup", {}, orgId),
    onSuccess: (res) => {
      if (res?.error) {
        toast.error(res.error);
        return;
      }
      toast.success("Backup queued", {
        description: "The POS will run it on its next command poll (~30s).",
      });
      backupsQ.refetch();
    },
    onError: (e: Error) => toast.error(e.message || "Backup failed to start"),
  });

  const backups: AdminBackup[] = backupsQ.data?.backups || [];
  const summary = backupsQ.data?.summary;
  const devices: CloudDevice[] = devicesQ.data?.devices || [];
  const usedMb = (Number(summary?.total_bytes || 0) / 1048576);
  const limitMb = 20480;
  const pct = Math.min(100, Math.round((usedMb / limitMb) * 100));
  const lastAt = summary?.last_backup || backups[0]?.created_at;
  const lastStatus = String(summary?.last_status || backups[0]?.status || "unknown");
  const okStatus = ["ok", "success", "complete", "completed"].includes(lastStatus.toLowerCase());
  const errMsg = backupsQ.data?.error || (backupsQ.isError ? "Could not load cloud backups" : "");

  return (
    <PageShell>
      <PageHeader
        eyebrow="MBT POS"
        title="Backup Center"
        description="Cloud backup metadata for your organization — restored from Supabase, not the local shop Command Center."
        actions={
          <Button variant="outline" onClick={() => { backupsQ.refetch(); devicesQ.refetch(); }}>
            <RefreshCw className="mr-1.5 h-4 w-4" />Refresh
          </Button>
        }
      />

      {backupsQ.isLoading ? (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">Loading cloud backups…</CardContent></Card>
      ) : errMsg && backups.length === 0 ? (
        <Card><CardContent className="flex gap-3 p-6 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {errMsg}
        </CardContent></Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatusCard
              icon={okStatus ? CheckCircle2 : AlertTriangle}
              ok={okStatus && Boolean(lastAt)}
              label="Last cloud backup"
              value={lastAt ? new Date(lastAt).toLocaleString() : "Never"}
              sub={lastStatus}
            />
            <StatusCard
              icon={Calendar}
              ok={backups.length > 0}
              label="Snapshots"
              value={String(summary?.count ?? backups.length)}
              sub={summary?.last_device_id || "org-scoped"}
            />
            <StatusCard
              icon={HardDrive}
              ok={pct < 80}
              label="Listed storage"
              value={`${(usedMb / 1024).toFixed(2)} GB`}
              sub={`of ${(limitMb / 1024).toFixed(0)} GB plan estimate`}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="font-display">Storage usage</CardTitle>
              <CardDescription>
                {(usedMb / 1024).toFixed(2)} GB across listed snapshots
                {summary?.last_mbt_version ? ` · last POS v${summary.last_mbt_version}` : ""}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Progress value={pct} className="h-3" />
              <p className="mt-2 text-xs text-muted-foreground">
                {pct}% of estimated plan — {pct > 80 ? "Consider archiving older backup files." : "Storage is healthy."}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="font-display">Backup history</CardTitle>
              <CardDescription>Newest cloud uploads recorded for this organization.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {backups.length === 0 ? (
                <p className="text-sm text-muted-foreground">No cloud backups yet for this organization.</p>
              ) : backups.slice(0, 40).map((b) => (
                <BackupRow
                  key={b.id || `${b.storage_path}-${b.created_at}`}
                  name={b.business_name || b.org_name || b.device_id || "Snapshot"}
                  date={b.created_at || ""}
                  status={b.status || b.backup_type || "ok"}
                  size={b.size_bytes ? `${(Number(b.size_bytes) / 1048576).toFixed(1)} MB` : "—"}
                  version={b.mbt_version}
                />
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="font-display">Queue backup on device</CardTitle>
              <CardDescription>
                Issues a cloud run_backup command. The live POS applies it on the next poll — does not use local /api/backup/run.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {devices.length === 0 ? (
                <p className="text-sm text-muted-foreground">No registered devices to command.</p>
              ) : devices.map((d) => (
                <div key={d.device_id || d.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-border/70 p-4">
                  <div className="grid h-9 w-9 place-items-center rounded-lg bg-primary/10 text-primary">
                    <MonitorSmartphone className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{d.computer_name || d.hostname || d.device_id}</div>
                    <div className="truncate font-mono text-xs text-muted-foreground">{d.device_id}</div>
                  </div>
                  <Button
                    size="sm"
                    disabled={!d.device_id || runMut.isPending}
                    onClick={() => runMut.mutate({ deviceId: d.device_id! })}
                  >
                    <CloudUpload className="mr-1.5 h-4 w-4" />
                    Backup now
                  </Button>
                </div>
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </PageShell>
  );
}

function StatusCard({ icon: Icon, ok, label, value, sub }: {
  icon: React.ComponentType<{ className?: string }>; ok: boolean; label: string; value: string; sub: string;
}) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-start gap-3">
          <div className={`grid h-10 w-10 place-items-center rounded-lg ${ok ? "bg-success/15 text-success" : "bg-destructive/15 text-destructive"}`}>
            <Icon className="h-5 w-5" />
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
            <div className="mt-1 font-display text-lg font-semibold">{value}</div>
            <div className="text-xs text-muted-foreground">{sub}</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function BackupRow({ name, date, status, size, version }: {
  name: string; date: string; status: string; size: string; version?: string;
}) {
  const ok = ["ok", "success", "complete", "completed"].includes(status.toLowerCase());
  return (
    <div className="flex items-center justify-between rounded-xl border border-border/70 p-4">
      <div className="flex items-center gap-3">
        <div className={`grid h-9 w-9 place-items-center rounded-lg ${ok ? "bg-success/15 text-success" : "bg-warning/15 text-warning"}`}>
          {ok ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
        </div>
        <div>
          <div className="font-medium">{name}</div>
          <div className="text-xs text-muted-foreground">
            {date ? new Date(date).toLocaleString() : "—"} · {size}
            {version ? ` · v${version}` : ""}
          </div>
        </div>
      </div>
      <Badge variant={ok ? "default" : "secondary"}>{status}</Badge>
    </div>
  );
}
