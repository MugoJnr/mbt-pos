import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  MonitorSmartphone, CheckCircle2, AlertTriangle, RefreshCw,
  Cpu, WifiOff, Wifi, Clock, ShieldCheck, Ban, Pencil,
} from "lucide-react";
import { useMemo, useState } from "react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  GET,
  approveCloudDevice,
  deactivateCloudDevice,
  listCloudDevices,
  listDeviceEvents,
  rejectCloudDevice,
  renameCloudDevice,
  type CloudDevice,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { toast } from "sonner";

export const Route = createFileRoute("/_app/devices")({
  component: DevicesPage,
  head: () => ({ meta: [{ title: "Devices | MugoByte" }] }),
});

type LicenseStatus = {
  state?: string;
  is_valid?: boolean;
  device_id?: string;
  plan_name?: string;
  plan?: string;
  expiry_date?: string;
  days_remaining?: number | string;
  activation_date?: string;
  source?: string;
  error?: string;
};

function approvalVariant(status?: string) {
  const s = (status || "pending").toLowerCase();
  if (s === "approved") return "default" as const;
  if (s === "rejected" || s === "deactivated") return "destructive" as const;
  return "secondary" as const;
}

function DevicesPage() {
  const { orgId } = useAuth();
  const qc = useQueryClient();
  const [busyId, setBusyId] = useState<string>("");

  const licQ = useQuery({
    queryKey: ["license-status"],
    queryFn: () => GET<LicenseStatus>("/license/status"),
  });
  const verQ = useQuery({
    queryKey: ["app-version"],
    queryFn: () => GET<Record<string, string>>("/version"),
  });
  const devicesQ = useQuery({
    queryKey: ["cloud-devices", orgId],
    queryFn: () => listCloudDevices(orgId),
  });
  const eventsQ = useQuery({
    queryKey: ["device-events", orgId],
    queryFn: () => listDeviceEvents(orgId, 25),
  });

  const lic = licQ.data || {};
  const ver = verQ.data;
  const localForbidden = lic.error === "Forbidden";
  const devices: CloudDevice[] = devicesQ.data?.devices || [];
  const pending = useMemo(
    () => devices.filter((d) => (d.approval_status || "pending").toLowerCase() === "pending"),
    [devices],
  );

  const deviceId = localForbidden ? "—" : (lic.device_id || "—");
  const state = localForbidden ? "unavailable" : (lic.state || "unknown");
  const isOnline = state === "active" || state === "expiring";

  const refreshAll = () => {
    licQ.refetch();
    verQ.refetch();
    devicesQ.refetch();
    eventsQ.refetch();
  };

  const act = useMutation({
    mutationFn: async (op: {
      kind: "approve" | "reject" | "deactivate" | "rename";
      id: string;
      name?: string;
    }) => {
      setBusyId(op.id);
      if (op.kind === "approve") return approveCloudDevice(op.id, orgId);
      if (op.kind === "reject") return rejectCloudDevice(op.id, orgId);
      if (op.kind === "deactivate") return deactivateCloudDevice(op.id, orgId);
      return renameCloudDevice(op.id, op.name || "", orgId);
    },
    onSuccess: (res, op) => {
      if (res.error) {
        toast.error(res.error);
        return;
      }
      toast.success(
        op.kind === "approve"
          ? "Device approved"
          : op.kind === "reject"
            ? "Device rejected"
            : op.kind === "deactivate"
              ? "Device deactivated"
              : "Device renamed",
      );
      qc.invalidateQueries({ queryKey: ["cloud-devices", orgId] });
      qc.invalidateQueries({ queryKey: ["device-events", orgId] });
    },
    onError: (e: Error) => toast.error(e.message || "Device action failed"),
    onSettled: () => setBusyId(""),
  });

  return (
    <PageShell>
      <PageHeader
        eyebrow="MBT POS"
        title="Devices & Activation"
        description="Approve new installations, monitor hardware, and manage license bindings for your organization."
        actions={
          <Button variant="outline" onClick={refreshAll}>
            <RefreshCw className="mr-1.5 h-4 w-4" />Refresh
          </Button>
        }
      />

      {devicesQ.isLoading && licQ.isLoading ? (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">Loading device information…</CardContent></Card>
      ) : (
        <>
          {localForbidden ? (
            <Card>
              <CardContent className="p-4 text-sm text-muted-foreground">
                Local install status is unavailable for this account. Organization cloud devices below are still accessible.
              </CardContent>
            </Card>
          ) : null}
          <div className="grid gap-4 sm:grid-cols-4">
            <Card>
              <CardContent className="p-5">
                <div className={`grid h-10 w-10 place-items-center rounded-lg ${isOnline ? "bg-success/15 text-success" : "bg-destructive/15 text-destructive"}`}>
                  {isOnline ? <Wifi className="h-5 w-5" /> : <WifiOff className="h-5 w-5" />}
                </div>
                <div className="mt-3 text-xs uppercase tracking-wide text-muted-foreground">Status</div>
                <div className="mt-1 font-display text-lg font-semibold capitalize">{state}</div>
                <div className="text-xs text-muted-foreground">{isOnline ? "Connected to license server" : "Offline or unactivated"}</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-5">
                <div className="grid h-10 w-10 place-items-center rounded-lg bg-primary/10 text-primary"><Cpu className="h-5 w-5" /></div>
                <div className="mt-3 text-xs uppercase tracking-wide text-muted-foreground">Hardware ID</div>
                <div className="mt-1 font-mono text-sm font-semibold break-all">{deviceId}</div>
                <div className="text-xs text-muted-foreground">Bound to this machine</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-5">
                <div className="grid h-10 w-10 place-items-center rounded-lg bg-info/15 text-info"><Clock className="h-5 w-5" /></div>
                <div className="mt-3 text-xs uppercase tracking-wide text-muted-foreground">Cloud devices</div>
                <div className="mt-1 font-display text-lg font-semibold">{devices.length}</div>
                <div className="text-xs text-muted-foreground">Registered to your organization</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-5">
                <div className="grid h-10 w-10 place-items-center rounded-lg bg-warning/15 text-warning"><ShieldCheck className="h-5 w-5" /></div>
                <div className="mt-3 text-xs uppercase tracking-wide text-muted-foreground">Approval queue</div>
                <div className="mt-1 font-display text-lg font-semibold">{pending.length}</div>
                <div className="text-xs text-muted-foreground">Awaiting admin decision</div>
              </CardContent>
            </Card>
          </div>

          {pending.length > 0 && (
            <Card className="border-warning/40">
              <CardHeader>
                <CardTitle className="font-display">Pending approvals</CardTitle>
                <CardDescription>New desktop installations must be approved before cloud sync is allowed.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {pending.map((d) => {
                  const key = d.device_id || d.id || "";
                  return (
                    <div key={key} className="flex flex-wrap items-center gap-3 rounded-xl border border-border/70 p-4">
                      <div className="grid h-8 w-8 place-items-center rounded-lg bg-warning/15 text-warning">
                        <MonitorSmartphone className="h-4 w-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="font-medium">{d.computer_name || d.hostname || d.device_id || "Device"}</div>
                        <div className="truncate font-mono text-xs text-muted-foreground">{d.device_id}</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {d.platform || d.os_info || "—"} · v{d.mbt_version || "—"}
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          disabled={busyId === key}
                          onClick={() => act.mutate({ kind: "approve", id: key })}
                        >
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busyId === key}
                          onClick={() => act.mutate({ kind: "reject", id: key })}
                        >
                          Reject
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="font-display">This device</CardTitle>
                <CardDescription>Current machine registered to your MBT POS license.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <DeviceRow label="Device ID" value={deviceId} mono />
                <DeviceRow label="Plan" value={localForbidden ? "—" : (lic.plan_name || lic.plan || "—")} />
                <DeviceRow label="Activation date" value={localForbidden ? "—" : (lic.activation_date || "—")} />
                <DeviceRow label="License source" value={localForbidden ? "unavailable" : (lic.source || "license_engine")} />
                <DeviceRow label="App version" value={ver?.version ? `v${ver.version}` : "—"} mono />
                <DeviceRow label="License state" value={state} />
                <div className="flex items-center gap-2 pt-2">
                  <Badge variant={isOnline ? "default" : "secondary"}>{state.toUpperCase()}</Badge>
                  {!localForbidden ? (
                    <Badge variant={lic.is_valid ? "default" : "destructive"}>
                      {lic.is_valid ? "Valid" : "Not valid"}
                    </Badge>
                  ) : null}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="font-display">Organization devices</CardTitle>
                <CardDescription>Live roster from Portal device registration.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {devicesQ.isLoading ? (
                  <p className="text-sm text-muted-foreground">Loading devices…</p>
                ) : devices.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
                    No cloud devices yet. Complete portal-first setup on the desktop POS to register this machine.
                  </div>
                ) : devices.map((d) => {
                  const key = d.device_id || d.id || "";
                  const status = (d.approval_status || (d.is_active === false ? "deactivated" : "approved")).toLowerCase();
                  return (
                    <div key={key} className="rounded-xl border border-border/70 p-4">
                      <div className="flex items-start gap-3">
                        <div className="grid h-8 w-8 place-items-center rounded-lg bg-primary/10 text-primary">
                          <MonitorSmartphone className="h-4 w-4" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="font-medium">{d.computer_name || d.hostname || d.device_id || "Device"}</div>
                          <div className="truncate font-mono text-xs text-muted-foreground">{d.device_id}</div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            {d.platform || d.os_info || "—"} · v{d.mbt_version || "—"} ·{" "}
                            {d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : "never"}
                          </div>
                          {d.last_sync_at && (
                            <div className="mt-0.5 text-xs text-muted-foreground">
                              Last sync: {new Date(d.last_sync_at).toLocaleString()} · {d.sync_status || "—"}
                            </div>
                          )}
                        </div>
                        <Badge variant={approvalVariant(status)}>{status}</Badge>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {status === "pending" && (
                          <>
                            <Button size="sm" disabled={busyId === key} onClick={() => act.mutate({ kind: "approve", id: key })}>
                              <ShieldCheck className="mr-1 h-3.5 w-3.5" />Approve
                            </Button>
                            <Button size="sm" variant="outline" disabled={busyId === key} onClick={() => act.mutate({ kind: "reject", id: key })}>
                              <Ban className="mr-1 h-3.5 w-3.5" />Reject
                            </Button>
                          </>
                        )}
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busyId === key}
                          onClick={() => {
                            const name = window.prompt("Computer name", d.computer_name || d.hostname || "");
                            if (name) act.mutate({ kind: "rename", id: key, name });
                          }}
                        >
                          <Pencil className="mr-1 h-3.5 w-3.5" />Rename
                        </Button>
                        {status !== "deactivated" && (
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busyId === key}
                            onClick={() => act.mutate({ kind: "deactivate", id: key })}
                          >
                            Deactivate
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="font-display">Device history</CardTitle>
              <CardDescription>Registration, approval, and management events for this organization.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {(eventsQ.data?.events || []).length === 0 ? (
                <p className="text-sm text-muted-foreground">No device events yet.</p>
              ) : (
                (eventsQ.data?.events || []).map((ev, idx) => {
                  const ok = String(ev.event_type || "").includes("approv") || String(ev.event_type || "") === "registered";
                  return (
                    <HistoryRow
                      key={String(ev.id || idx)}
                      icon={ok ? CheckCircle2 : AlertTriangle}
                      ok={ok}
                      event={String(ev.event_type || "event")}
                      detail={JSON.stringify(ev.details || {})}
                      date={ev.created_at ? new Date(String(ev.created_at)).toLocaleString() : "—"}
                    />
                  );
                })
              )}
            </CardContent>
          </Card>
        </>
      )}
    </PageShell>
  );
}

function DeviceRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={`font-medium ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

function HistoryRow({ icon: Icon, ok, event, detail, date }: {
  icon: React.ComponentType<{ className?: string }>; ok: boolean; event: string; detail: string; date: string;
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-border/70 p-4">
      <div className={`grid h-8 w-8 place-items-center rounded-lg ${ok ? "bg-success/15 text-success" : "bg-warning/15 text-warning"}`}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="font-medium capitalize">{event.replace(/_/g, " ")}</div>
        <div className="truncate text-xs text-muted-foreground">{detail}</div>
        <div className="mt-0.5 text-xs text-muted-foreground">{date}</div>
      </div>
    </div>
  );
}
