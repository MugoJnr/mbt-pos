import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  KeyRound, RefreshCw, Download, CheckCircle2, AlertTriangle, Clock, Plus, Copy,
  Ban, CalendarPlus, ShieldAlert, ArrowRightLeft, Wifi,
} from "lucide-react";
import { toast } from "sonner";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import {
  GET,
  createCloudLicense,
  listCloudLicenses,
  activateCloudLicense,
  revokeCloudLicense,
  suspendCloudLicense,
  unsuspendCloudLicense,
  renewCloudLicense,
  forceValidateCloudLicense,
  transferCloudLicense,
  licenseHistory,
  type CloudLicense,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { downloadApi, exportQuery } from "@/lib/download";

export const Route = createFileRoute("/_admin/admin/licenses")({
  component: AdminLicensesPage,
  head: () => ({ meta: [{ title: "Licenses | MugoByte" }] }),
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
  license_key?: string;
  requires_online?: boolean;
  offline_days?: number;
  tampered?: boolean;
  revoked?: boolean;
  error?: string;
};

function AdminLicensesPage() {
  const { orgId } = useAuth();
  const qc = useQueryClient();
  const [exporting, setExporting] = useState(false);
  const [activateKey, setActivateKey] = useState("");
  const [plan, setPlan] = useState("trial");
  const [renewDays, setRenewDays] = useState(30);
  const [historyId, setHistoryId] = useState<string>("");
  const [transferOld, setTransferOld] = useState("");
  const [transferNew, setTransferNew] = useState("");
  const [transferLic, setTransferLic] = useState("");

  const licQ = useQuery({
    queryKey: ["license-status"],
    queryFn: () => GET<LicenseStatus>("/license/status"),
  });
  const cloudQ = useQuery({
    queryKey: ["cloud-licenses", orgId],
    queryFn: () => listCloudLicenses(orgId),
  });
  const histQ = useQuery({
    queryKey: ["license-history", historyId],
    queryFn: () => licenseHistory(historyId),
    enabled: Boolean(historyId),
  });
  const versionQ = useQuery({
    queryKey: ["app-version"],
    queryFn: () => GET<Record<string, string>>("/version"),
  });

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["license-status"] });
    qc.invalidateQueries({ queryKey: ["cloud-licenses"] });
    if (historyId) qc.invalidateQueries({ queryKey: ["license-history", historyId] });
  };

  const createMut = useMutation({
    mutationFn: () => createCloudLicense(plan, `Issued from admin (${plan})`, orgId),
    onSuccess: (res) => {
      if (res?.error || !res?.license) {
        toast.error(res?.error || "Failed to create license");
        return;
      }
      toast.success("License created", { description: res.license.license_key });
      refreshAll();
    },
  });

  const activateMut = useMutation({
    mutationFn: (key?: string) => activateCloudLicense((key || activateKey).trim(), undefined, orgId),
    onSuccess: (res) => {
      if (res?.error || !res?.ok) {
        toast.error(res?.error || "Activation failed");
        return;
      }
      toast.success(res.message || "Activated on this device");
      setActivateKey("");
      refreshAll();
    },
  });

  const actionMut = useMutation({
    mutationFn: async (args: { op: string; id: string; days?: number }) => {
      if (args.op === "revoke") return revokeCloudLicense(args.id);
      if (args.op === "suspend") return suspendCloudLicense(args.id);
      if (args.op === "unsuspend") return unsuspendCloudLicense(args.id);
      if (args.op === "renew") return renewCloudLicense(args.id, args.days || renewDays);
      if (args.op === "force") return forceValidateCloudLicense(args.id);
      throw new Error("Unknown op");
    },
    onSuccess: (res, vars) => {
      if ((res as { error?: string })?.error) {
        toast.error((res as { error?: string }).error);
        return;
      }
      const n = (res as { commands_issued?: number })?.commands_issued ?? 0;
      const status = (res as { license?: CloudLicense })?.license?.status;
      if (n === 0 && (vars.op === "suspend" || vars.op === "revoke")) {
        toast.success(`${vars.op} saved in cloud`, {
          description: status
            ? `Status is now ${status}. No online POS device was linked — it will lock on next phone-home.`
            : "No online POS device was linked — it will lock on next phone-home.",
        });
      } else {
        toast.success(`${vars.op} sent`, {
          description: `Pushed to ${n} device(s). Online POS applies within ~30s; offline POS within ~15 min of reconnect.`,
        });
      }
      refreshAll();
      setHistoryId(vars.id);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const transferMut = useMutation({
    mutationFn: () => transferCloudLicense(transferLic, transferOld.trim(), transferNew.trim()),
    onSuccess: (res) => {
      if (res?.error || !res?.ok) {
        toast.error(res?.error || "Transfer failed");
        return;
      }
      toast.success(res.message || "Device transferred — old device will revoke on next poll");
      refreshAll();
    },
  });

  const lic = licQ.data || {};
  const state = lic.state || "unknown";
  const isActive = state === "active";
  const isExpiring = state === "expiring";
  const cloudLicenses: CloudLicense[] = cloudQ.data?.licenses || [];

  async function doExport() {
    try {
      setExporting(true);
      const qs = exportQuery({ type: "license", format: "xlsx" });
      await downloadApi(`/reports/export?${qs}`, "MBT_Licenses.xlsx");
      toast.success("License report exported");
    } catch (e: unknown) {
      toast.error((e as Error).message || "Export failed");
    } finally {
      setExporting(false);
    }
  }

  function copyKey(key?: string) {
    if (!key) return;
    navigator.clipboard.writeText(key);
    toast.success("License key copied");
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="Admin"
        title="License Control Plane"
        description="Issue, activate, renew, revoke, transfer and force online validation — changes push to POS devices within ~30 seconds."
        actions={
          <>
            <Button variant="outline" onClick={() => { licQ.refetch(); cloudQ.refetch(); versionQ.refetch(); }}>
              <RefreshCw className="mr-1.5 h-4 w-4" />Refresh
            </Button>
            <Button variant="outline" disabled={exporting} onClick={doExport}>
              <Download className="mr-1.5 h-4 w-4" />Export
            </Button>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-4">
        <Card className={isActive ? "border-success/30" : isExpiring ? "border-warning/30" : "border-destructive/30"}>
          <CardContent className="p-5">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
              {isActive ? <CheckCircle2 className="h-5 w-5 text-success" /> : <AlertTriangle className="h-5 w-5 text-warning" />}
            </div>
            <div className="mt-3 text-xs uppercase tracking-wide text-muted-foreground">This POS</div>
            <div className="mt-1 font-display text-xl font-semibold capitalize">{state}</div>
            <Badge className="mt-2" variant={lic.is_valid ? "default" : "destructive"}>{lic.is_valid ? "Valid" : "Locked"}</Badge>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-info/15 text-info"><Clock className="h-5 w-5" /></div>
            <div className="mt-3 text-xs uppercase tracking-wide text-muted-foreground">Offline days</div>
            <div className="mt-1 font-display text-xl font-semibold">{lic.offline_days ?? 0}</div>
            <div className="text-xs text-muted-foreground">{lic.requires_online ? "Must connect to cloud" : "Within grace window"}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary"><KeyRound className="h-5 w-5" /></div>
            <div className="mt-3 text-xs uppercase tracking-wide text-muted-foreground">Cloud licenses</div>
            <div className="mt-1 font-display text-xl font-semibold">{cloudLicenses.length}</div>
            <div className="text-xs text-muted-foreground">Plan: {lic.plan_name || lic.plan || "—"}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-destructive/10 text-destructive"><ShieldAlert className="h-5 w-5" /></div>
            <div className="mt-3 text-xs uppercase tracking-wide text-muted-foreground">Security</div>
            <div className="mt-1 font-display text-sm font-semibold">
              {lic.tampered ? "TAMPERED" : lic.revoked ? "REVOKED" : "OK"}
            </div>
            <div className="text-xs text-muted-foreground">Clock / device binding</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="font-display">Cloud licenses</CardTitle>
            <CardDescription>Admin actions update Supabase and push remote commands to every activated POS.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <select className="h-9 rounded-md border border-border bg-background px-3 text-sm" value={plan} onChange={(e) => setPlan(e.target.value)}>
                {["trial", "basic", "monthly", "pro", "annual", "lifetime"].map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
              <Button onClick={() => createMut.mutate()} disabled={createMut.isPending}>
                <Plus className="mr-1.5 h-4 w-4" />{createMut.isPending ? "Creating…" : "Issue license"}
              </Button>
              <Input type="number" className="w-24" value={renewDays} onChange={(e) => setRenewDays(Number(e.target.value) || 30)} title="Renew days" />
            </div>
            {cloudQ.isLoading ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : cloudLicenses.length === 0 ? (
              <p className="text-sm text-muted-foreground">No cloud licenses yet.</p>
            ) : (
              <div className="space-y-3">
                {cloudLicenses.map((row) => (
                  <div key={row.id || row.license_key} className="rounded-xl border border-border/70 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="font-mono text-sm font-semibold">{row.license_key}</div>
                          <Badge variant={
                            row.status === "active" || row.status === "trial" ? "default"
                              : row.status === "suspended" ? "secondary"
                                : "destructive"
                          }>
                            {row.status || "unknown"}
                          </Badge>
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {row.plan} · {row.activated_devices ?? 0}/{row.max_devices ?? 1} devices
                          {row.org_id ? ` · org ${String(row.org_id).slice(0, 8)}…` : ""}
                        </div>
                        <div className="text-xs text-muted-foreground">Expires {row.expires_at ? new Date(row.expires_at).toLocaleDateString() : "—"}</div>
                      </div>
                      <Button variant="outline" size="sm" onClick={() => copyKey(row.license_key)}><Copy className="h-3.5 w-3.5" /></Button>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      <Button size="sm" variant="outline" onClick={() => activateMut.mutate(row.license_key)} disabled={row.status === "suspended" || row.status === "revoked"}>Activate here</Button>
                      <Button size="sm" variant="outline" onClick={() => actionMut.mutate({ op: "renew", id: row.id!, days: renewDays })}>
                        <CalendarPlus className="mr-1 h-3.5 w-3.5" />Extend
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => actionMut.mutate({ op: "force", id: row.id! })}>
                        <Wifi className="mr-1 h-3.5 w-3.5" />Force online
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => { setHistoryId(row.id || ""); }}>History</Button>
                      {row.status === "suspended" ? (
                        <Button size="sm" variant="outline" onClick={() => actionMut.mutate({ op: "unsuspend", id: row.id! })}>Unsuspend</Button>
                      ) : (
                        <Button size="sm" variant="outline" disabled={row.status === "revoked"} onClick={() => actionMut.mutate({ op: "suspend", id: row.id! })}>Suspend</Button>
                      )}
                      <Button size="sm" variant="destructive" disabled={row.status === "revoked"} onClick={() => {
                        if (confirm("Revoke this license on all devices?")) actionMut.mutate({ op: "revoke", id: row.id! });
                      }}>
                        <Ban className="mr-1 h-3.5 w-3.5" />Revoke
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="font-display">Activate / transfer</CardTitle>
              <CardDescription>Bind a key to this machine, or move a license between hardware IDs.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Input placeholder="MBT-TRI-XXXX-XXXX-XXXX" value={activateKey} onChange={(e) => setActivateKey(e.target.value)} />
              <Button className="w-full" disabled={!activateKey.trim() || activateMut.isPending} onClick={() => activateMut.mutate()}>
                {activateMut.isPending ? "Activating…" : "Activate on this device"}
              </Button>
              <Separator />
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium"><ArrowRightLeft className="h-4 w-4" /> Device transfer</div>
                <select className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm" value={transferLic} onChange={(e) => setTransferLic(e.target.value)}>
                  <option value="">Select license…</option>
                  {cloudLicenses.map((l) => (
                    <option key={l.id} value={l.id}>{l.license_key} ({l.plan})</option>
                  ))}
                </select>
                <Input placeholder="Old device ID" value={transferOld} onChange={(e) => setTransferOld(e.target.value)} />
                <Input placeholder="New device ID" value={transferNew} onChange={(e) => setTransferNew(e.target.value)} />
                <Button
                  variant="outline"
                  className="w-full"
                  disabled={!transferLic || !transferOld.trim() || !transferNew.trim() || transferMut.isPending}
                  onClick={() => transferMut.mutate()}
                >
                  Transfer license
                </Button>
              </div>
              <Separator />
              <div className="space-y-2 text-sm">
                {[
                  ["Device", lic.device_id || "—"],
                  ["Source", lic.source || "—"],
                  ["App", versionQ.data?.version ? `v${versionQ.data.version}` : "—"],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between"><span className="text-muted-foreground">{label}</span><span className="font-mono">{value}</span></div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="font-display">License history</CardTitle>
              <CardDescription>{historyId ? "Cloud license_history events" : "Select History on a license"}</CardDescription>
            </CardHeader>
            <CardContent className="max-h-64 space-y-2 overflow-y-auto">
              {!historyId ? (
                <p className="text-sm text-muted-foreground">No license selected.</p>
              ) : histQ.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
              ) : (histQ.data?.history || []).length === 0 ? (
                <p className="text-sm text-muted-foreground">No history yet.</p>
              ) : (histQ.data?.history || []).map((h: any, i: number) => (
                <div key={h.id || i} className="rounded-lg border border-border/60 px-3 py-2 text-sm">
                  <div className="font-medium capitalize">{h.action}</div>
                  <div className="text-xs text-muted-foreground">{h.created_at ? new Date(h.created_at).toLocaleString() : "—"}</div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </PageShell>
  );
}
