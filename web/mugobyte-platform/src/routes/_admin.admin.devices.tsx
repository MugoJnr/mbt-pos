import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MonitorSmartphone, RefreshCw, Wifi } from "lucide-react";
import { toast } from "sonner";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getAdminOverview, issueCloudCommand, isCloudDeviceOnline, type CloudDevice } from "@/lib/api";

export const Route = createFileRoute("/_admin/admin/devices")({
  component: Page,
  head: () => ({ meta: [{ title: "Devices | MugoByte" }] }),
});

function Page() {
  const qc = useQueryClient();
  const devicesQ = useQuery({
    queryKey: ["admin-overview"],
    queryFn: getAdminOverview,
    retry: 1,
  });
  const devices: Array<CloudDevice & { org_name?: string }> = devicesQ.data?.devices || [];
  const isOnline = isCloudDeviceOnline;
  const online = devices.filter(isOnline).length;

  const cmdMut = useMutation({
    mutationFn: ({ deviceId, command, orgId }: { deviceId: string; command: string; orgId: string }) =>
      issueCloudCommand(deviceId, command, {}, orgId),
    onSuccess: (res, vars) => {
      if (res?.error) {
        toast.error(res.error);
        return;
      }
      toast.success(`${vars.command} queued`, { description: "POS will apply within ~30 seconds." });
      qc.invalidateQueries({ queryKey: ["admin-overview"] });
    },
  });

  return (
    <PageShell>
      <PageHeader
        eyebrow="Admin"
        title="Devices"
        description="Registered POS hardware. Push force-validate or refresh-license commands to any device."
        actions={
          <Button variant="outline" onClick={() => devicesQ.refetch()}>
            <RefreshCw className="mr-1.5 h-4 w-4" />Refresh
          </Button>
        }
      />

      {devicesQ.data?.errors?.devices ? (
        <Card className="border-destructive/40">
          <CardContent className="p-4 text-sm text-destructive">{devicesQ.data.errors.devices}</CardContent>
        </Card>
      ) : null}

      <div className="mb-4 grid gap-4 sm:grid-cols-3">
        <Card><CardContent className="p-5"><div className="text-xs uppercase text-muted-foreground">Total</div><div className="mt-1 font-display text-2xl font-semibold">{devices.length}</div></CardContent></Card>
        <Card><CardContent className="p-5"><div className="text-xs uppercase text-muted-foreground">Online</div><div className="mt-1 font-display text-2xl font-semibold">{online}</div><div className="text-xs text-muted-foreground">Seen within 5 minutes</div></CardContent></Card>
        <Card><CardContent className="p-5"><div className="text-xs uppercase text-muted-foreground">Offline</div><div className="mt-1 font-display text-2xl font-semibold">{devices.length - online}</div></CardContent></Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="font-display">Device roster</CardTitle>
          <CardDescription>OS, version, last seen — remote commands poll every 30s on desktop.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {devicesQ.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : devices.length === 0 ? (
            <p className="text-sm text-muted-foreground">No devices registered yet.</p>
          ) : devices.map((d) => (
            <div key={d.id || d.device_id} className="flex flex-wrap items-start gap-3 rounded-xl border border-border/70 p-4">
              <div className="grid h-9 w-9 place-items-center rounded-lg bg-primary/10 text-primary">
                <MonitorSmartphone className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="font-medium">{d.computer_name || d.hostname || "Device"}</div>
                <div className="truncate font-mono text-xs text-muted-foreground">{d.device_id}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {d.os_info || d.platform || "—"} · v{d.mbt_version || "—"} · last seen {d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : "never"}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{d.org_name || d.org_id || "Unlinked organization"}</div>
              </div>
              <Badge variant={isOnline(d) ? "default" : "secondary"}>
                {isOnline(d) ? "Online" : d.is_active === false ? "Disabled" : "Offline"}
              </Badge>
              <div className="flex w-full flex-wrap gap-1.5 sm:w-auto">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!d.device_id || !d.org_id || cmdMut.isPending}
                  onClick={() => cmdMut.mutate({ deviceId: d.device_id!, command: "force_validate", orgId: d.org_id! })}
                >
                  <Wifi className="mr-1 h-3.5 w-3.5" />Force online
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!d.device_id || !d.org_id || cmdMut.isPending}
                  onClick={() => cmdMut.mutate({ deviceId: d.device_id!, command: "refresh_license", orgId: d.org_id! })}
                >
                  Refresh license
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!d.device_id || !d.org_id || cmdMut.isPending}
                  onClick={() => cmdMut.mutate({ deviceId: d.device_id!, command: "run_backup", orgId: d.org_id! })}
                >
                  Backup now
                </Button>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </PageShell>
  );
}
