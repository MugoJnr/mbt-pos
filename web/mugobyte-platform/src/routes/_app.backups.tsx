import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2, AlertTriangle, RefreshCw,
  Calendar, HardDrive,
} from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { GET } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/_app/backups")({
  component: BackupsPage,
  head: () => ({ meta: [{ title: "Backup Center | MugoByte" }] }),
});

type BackupStatus = {
  id?: string;
  business_id?: string;
  device_id?: string;
  size_bytes?: number;
  mbt_version?: string;
  schema_version?: number;
  reason?: string;
  created_at?: string;
};

type BackupResponse = {
  backups?: BackupStatus[];
  error?: string;
};

function BackupsPage() {
  const { orgId } = useAuth();
  const statusQ = useQuery({
    queryKey: ["backup-status", orgId],
    queryFn: () => GET<BackupResponse>("/cloud/backups", { org_id: orgId }),
    refetchInterval: 30_000,
    enabled: Boolean(orgId),
  });
  const backups = statusQ.data?.backups || [];
  const latest = backups[0];
  const usedBytes = backups.reduce((total, backup) => total + (backup.size_bytes || 0), 0);
  const usedMb = usedBytes / (1024 * 1024);

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
          </>
        }
      />

      {!orgId ? (
        <Card>
          <CardContent className="p-8 text-center">
            <AlertTriangle className="mx-auto mb-3 h-5 w-5 text-warning" />
            <p className="font-medium">Select a business to view its backups</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Backups are isolated by business. Choose the shop from the Business menu above.
            </p>
          </CardContent>
        </Card>
      ) : statusQ.isLoading ? (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">Loading backup status…</CardContent></Card>
      ) : statusQ.data?.error ? (
        <Card><CardContent className="flex gap-3 p-6 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {statusQ.data.error}
        </CardContent></Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatusCard
              icon={latest ? CheckCircle2 : AlertTriangle}
              ok={Boolean(latest)}
              label="Last backup"
              value={latest?.created_at ? latest.created_at.slice(0, 19).replace("T", " ") : "Never"}
              sub={latest ? "Cloud snapshot" : "No snapshot yet"}
            />
            <StatusCard
              icon={Calendar}
              ok
              label="Snapshots"
              value={String(backups.length)}
              sub="Recent cloud history"
            />
            <StatusCard
              icon={HardDrive}
              ok
              label="Storage used"
              value={`${usedMb.toFixed(1)} MB`}
              sub="Shown history"
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="font-display">Storage usage</CardTitle>
              <CardDescription>{usedMb.toFixed(2)} MB across the recent cloud snapshots shown here.</CardDescription>
            </CardHeader>
            <CardContent>
              <Progress value={backups.length ? 100 : 0} className="h-3" />
              <p className="mt-2 text-xs text-muted-foreground">Cloud storage is private to the selected business. Run a new backup in MBT POS.</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="font-display">Backup history</CardTitle>
              <CardDescription>Recent automated and manual backup runs.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {backups.length ? (
                backups.map((backup, index) => (
                  <BackupRow
                    key={backup.id || `${backup.created_at || "backup"}-${index}`}
                    name={index === 0 ? "Latest backup" : `Backup ${index + 1}`}
                    date={backup.created_at || ""}
                    status="ok"
                    size={backup.size_bytes ? `${(backup.size_bytes / (1024 * 1024)).toFixed(1)} MB` : "—"}
                  />
                ))
              ) : (
                <p className="text-sm text-muted-foreground">No backup history yet. Run your first backup now.</p>
              )}
              <div className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
                Restore is performed inside MBT POS so the application can check compatibility and preserve a pre-restore copy of the shop database.
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
        <span className="text-xs text-muted-foreground">Restore in MBT POS</span>
      </div>
    </div>
  );
}
