import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  CloudUpload, CheckCircle2, AlertTriangle, RefreshCw,
  Download, Calendar, HardDrive,
} from "lucide-react";
import { toast } from "sonner";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { GET, POST } from "@/lib/api";

export const Route = createFileRoute("/_app/backups")({
  component: BackupsPage,
  head: () => ({ meta: [{ title: "Backup Center | MugoByte" }] }),
});

type BackupStatus = {
  enabled?: boolean;
  provider?: string;
  last_backup?: string;
  status?: string;
  size_mb?: number;
  schedule?: string;
  storage_used_mb?: number;
  storage_limit_mb?: number;
  error?: string;
};

function BackupsPage() {
  const statusQ = useQuery({
    queryKey: ["backup-status"],
    queryFn: () => GET<BackupStatus>("/backup/status"),
    refetchInterval: 30_000,
  });

  const runMut = useMutation({
    mutationFn: () => POST("/backup/run"),
    onSuccess: () => {
      toast.success("Backup started");
      statusQ.refetch();
    },
    onError: () => toast.error("Backup failed to start"),
  });

  const s = statusQ.data || {};
  const usedMb = s.storage_used_mb ?? 0;
  const limitMb = s.storage_limit_mb ?? 20480;
  const pct = Math.round((usedMb / limitMb) * 100);

  return (
    <PageShell>
      <PageHeader
        eyebrow="MBT POS"
        title="Backup Center"
        description="Cloud backups, restoration points and storage usage synchronized from the MBT POS backend."
        actions={
          <>
            <Button variant="outline" onClick={() => statusQ.refetch()}>
              <RefreshCw className="mr-1.5 h-4 w-4" />Refresh
            </Button>
            <Button onClick={() => runMut.mutate()} disabled={runMut.isPending}>
              <CloudUpload className="mr-1.5 h-4 w-4" />
              {runMut.isPending ? "Starting…" : "Backup now"}
            </Button>
          </>
        }
      />

      {statusQ.isLoading ? (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">Loading backup status…</CardContent></Card>
      ) : s.error && !s.last_backup ? (
        <Card><CardContent className="flex gap-3 p-6 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {s.error}
        </CardContent></Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatusCard
              icon={s.status === "success" || s.status === "ok" ? CheckCircle2 : AlertTriangle}
              ok={s.status === "success" || s.status === "ok"}
              label="Last backup"
              value={s.last_backup ? s.last_backup.slice(0, 19).replace("T", " ") : "Never"}
              sub={s.status ?? "unknown"}
            />
            <StatusCard
              icon={Calendar}
              ok={Boolean(s.schedule)}
              label="Schedule"
              value={s.schedule ?? "Not configured"}
              sub={s.provider ?? "local"}
            />
            <StatusCard
              icon={HardDrive}
              ok={pct < 80}
              label="Storage used"
              value={`${(usedMb / 1024).toFixed(1)} GB`}
              sub={`of ${(limitMb / 1024).toFixed(0)} GB`}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="font-display">Storage usage</CardTitle>
              <CardDescription>{(usedMb / 1024).toFixed(2)} GB used of {(limitMb / 1024).toFixed(0)} GB total</CardDescription>
            </CardHeader>
            <CardContent>
              <Progress value={pct} className="h-3" />
              <p className="mt-2 text-xs text-muted-foreground">{pct}% — {pct > 80 ? "Consider archiving older backup files." : "Storage is healthy."}</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="font-display">Backup history</CardTitle>
              <CardDescription>Recent automated and manual backup runs.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {s.last_backup ? (
                <BackupRow
                  name="Latest backup"
                  date={s.last_backup}
                  status={s.status ?? "ok"}
                  size={s.size_mb ? `${s.size_mb.toFixed(1)} MB` : "—"}
                />
              ) : (
                <p className="text-sm text-muted-foreground">No backup history yet. Run your first backup now.</p>
              )}
              <div className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
                Full backup history with individual restore points is reserved for the MugoByte cloud backup service integration. The backend endpoint is <code>/api/backup/status</code>.
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </PageShell>
  );
}

function StatusCard({ icon: Icon, ok, label, value, sub }: { icon: React.ComponentType<{ className?: string }>; ok: boolean; label: string; value: string; sub: string }) {
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

function BackupRow({ name, date, status, size }: { name: string; date: string; status: string; size: string }) {
  const ok = status === "success" || status === "ok";
  return (
    <div className="flex items-center justify-between rounded-xl border border-border/70 p-4">
      <div className="flex items-center gap-3">
        <div className={`grid h-9 w-9 place-items-center rounded-lg ${ok ? "bg-success/15 text-success" : "bg-warning/15 text-warning"}`}>
          {ok ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
        </div>
        <div>
          <div className="font-medium">{name}</div>
          <div className="text-xs text-muted-foreground">{date.slice(0, 19).replace("T", " ")} · {size}</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant={ok ? "default" : "secondary"}>{status}</Badge>
        <Button variant="outline" size="sm"><Download className="mr-1 h-3.5 w-3.5" />Download</Button>
      </div>
    </div>
  );
}
