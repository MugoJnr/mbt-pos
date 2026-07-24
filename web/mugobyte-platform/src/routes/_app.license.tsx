import type { ReactNode } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  KeyRound, Cpu, CalendarClock, ShieldCheck, BadgeCheck, RefreshCw, Copy, Link2, HardDrive,
} from "lucide-react";
import { toast } from "sonner";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { GET, activateCloudLicense, listCloudLicenses, type CloudLicense } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { LICENSE_PRODUCTS } from "@/lib/platform";

export const Route = createFileRoute("/_app/license")({
  component: License,
  head: () => ({ meta: [{ title: "Licenses | MugoByte" }] }),
});

function productLabel(productId?: string | null) {
  const id = (productId || "mbt-pos").toLowerCase();
  const hit = LICENSE_PRODUCTS.find((p) => p.id === id);
  return hit?.name || productId || "MBT POS";
}

function friendlyState(state?: string) {
  const s = (state || "unknown").toLowerCase();
  if (s === "active") return "Active";
  if (s === "expiring") return "Expiring soon";
  if (s === "expired") return "Expired";
  if (s === "warning" || s === "critical") return s === "critical" ? "Critical" : "Warning";
  if (s === "tampered") return "Needs attention";
  if (s === "inactive" || s === "revoked") return s === "revoked" ? "Revoked" : "Inactive";
  if (s === "unknown" || !state) return "Not yet activated";
  return state.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function friendlySource(source?: string | null) {
  const s = (source || "").toLowerCase();
  if (!s || s === "—" || s === "-") return "Waiting for activation";
  if (s === "fallback") return "Local / not activated online";
  if (s === "cloud" || s === "platform") return "Cloud activated";
  if (s === "local") return "Local license file";
  return source || "Waiting for activation";
}

function displayOrDash(value?: string | null, empty = "Not set yet") {
  const v = (value ?? "").toString().trim();
  if (!v || v === "—" || v === "-" || v.toLowerCase() === "unknown") return empty;
  return v;
}

function toneForState(state?: string) {
  const s = (state || "").toLowerCase();
  if (s === "active" || s === "expiring" || s === "claimed") return "default" as const;
  if (s === "warning" || s === "critical" || s === "reserved") return "secondary" as const;
  if (s === "expired" || s === "tampered" || s === "inactive" || s === "revoked") return "destructive" as const;
  return "outline" as const;
}

function claimLabel(status?: string | null) {
  const s = (status || "unassigned").toLowerCase();
  if (s === "claimed") return "Claimed";
  if (s === "reserved") return "Reserved";
  if (s === "unassigned") return "Unassigned";
  return status || "—";
}

function hwBindingStatus(row: CloudLicense) {
  const reserved = (row.reserved_device_id || "").trim();
  const claim = (row.claim_status || "").toLowerCase();
  if (!reserved) return { label: "No hardware lock", detail: "Any approved device in your org can activate this key." };
  if (claim === "claimed") return { label: "Bound to device", detail: `Locked to ${reserved}` };
  return { label: "Hardware reserved", detail: `Will bind on first claim to ${reserved}` };
}

function License() {
  const { orgId } = useAuth();
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [productFilter, setProductFilter] = useState<string>("all");
  const licQ = useQuery({ queryKey: ["license-status"], queryFn: () => GET<any>("/license/status") });
  const versionQ = useQuery({ queryKey: ["app-version"], queryFn: () => GET<any>("/version") });
  const cloudQ = useQuery({
    queryKey: ["cloud-licenses", orgId],
    queryFn: () => listCloudLicenses(orgId),
  });

  const activateMut = useMutation({
    mutationFn: () => activateCloudLicense(key.trim(), undefined, orgId),
    onSuccess: (res) => {
      if (res?.error || !res?.ok) {
        toast.error(res?.error || "Activation failed");
        return;
      }
      toast.success(res.message || "License activated");
      setKey("");
      qc.invalidateQueries({ queryKey: ["license-status"] });
      qc.invalidateQueries({ queryKey: ["cloud-licenses"] });
    },
  });

  const copyText = async (label: string, value?: string | null) => {
    const v = (value || "").trim();
    if (!v) {
      toast.error(`No ${label} to copy`);
      return;
    }
    try {
      await navigator.clipboard.writeText(v);
      toast.success(`${label} copied`);
    } catch {
      toast.error("Clipboard unavailable");
    }
  };

  const lic = licQ.data || {};
  const localForbidden = lic.error === "Forbidden";
  const state = String(lic.state || "unknown");
  const planName = lic.plan_name || lic.plan || "—";
  const expiry = lic.expiry_date || "—";
  const device = lic.device_id || "—";
  const days = lic.days_remaining;
  const ver = versionQ.data?.version || "—";
  const cloudLicenses: CloudLicense[] = cloudQ.data?.licenses || [];

  const filtered = useMemo(() => {
    if (productFilter === "all") return cloudLicenses;
    return cloudLicenses.filter(
      (row) => (row.product_id || "mbt-pos").toLowerCase() === productFilter,
    );
  }, [cloudLicenses, productFilter]);

  const productCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const row of cloudLicenses) {
      const id = (row.product_id || "mbt-pos").toLowerCase();
      counts[id] = (counts[id] || 0) + 1;
    }
    return counts;
  }, [cloudLicenses]);

  return (
    <PageShell>
      <PageHeader
        eyebrow="MugoByte · Licenses"
        title="License, Activation & Devices"
        description="Cloud seats for MBT POS, Pulse, and other MugoByte products — plus local engine status when available."
        actions={<Button variant="outline" onClick={() => { licQ.refetch(); cloudQ.refetch(); }}><RefreshCw className="mr-1.5 h-4 w-4" />Refresh</Button>}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
        {localForbidden ? (
          <Card className="lg:col-span-2">
            <CardContent className="p-6 text-sm text-muted-foreground">
              Local install status is unavailable for this account. Organization cloud licenses below are still fully accessible.
            </CardContent>
          </Card>
        ) : (
          <>
            <Card>
              <CardHeader>
                <div className="flex items-center gap-3">
                  <div className="grid h-11 w-11 place-items-center rounded-xl bg-primary/10 text-primary"><ShieldCheck className="h-5 w-5" /></div>
                  <div>
                    <CardTitle className="font-display">
                      {displayOrDash(planName === "—" ? "" : planName, "MBT POS")}
                    </CardTitle>
                    <CardDescription>Local engine status mirrored from MugoByte Platform when activated online.</CardDescription>
                  </div>
                  <div className="ml-auto"><Badge variant={toneForState(state)}>{friendlyState(state)}</Badge></div>
                </div>
              </CardHeader>
              <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <Info icon={<CalendarClock className="h-4 w-4" />} label="Expiry" value={displayOrDash(expiry === "—" ? "" : expiry, "Not set yet") + (days != null && days !== "" && expiry && expiry !== "—" ? ` · ${days}d left` : "")} />
                <Info icon={<Cpu className="h-4 w-4" />} label="Device" value={displayOrDash(String(device === "—" ? "" : device), "No device bound")} mono />
                <Info icon={<KeyRound className="h-4 w-4" />} label="App version" value={`v${ver}`} mono />
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="font-display">Validity</CardTitle></CardHeader>
              <CardContent className="space-y-4 text-sm">
                {lic.is_valid ? (
                  <>
                    <Row label="Valid for use" value="Yes" />
                    <Row label="Activation date" value={displayOrDash(lic.activation_date, "Not activated yet")} />
                    <Row label="Plan code" value={displayOrDash(lic.plan, "No plan yet")} mono />
                    <Row label="Source" value={friendlySource(lic.source)} />
                  </>
                ) : (
                    <div className="rounded-xl border border-dashed border-border/80 bg-muted/20 p-4">
                    <p className="font-medium text-foreground">Not activated yet</p>
                    <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                      Paste a cloud license key below to bind this workspace. Local engine status
                      stays empty until activation succeeds.
                    </p>
                    <ol className="mt-3 list-decimal space-y-1.5 pl-4 text-xs text-muted-foreground">
                      <li>Copy a key from Organization licenses (or from your purchase email).</li>
                      <li>Paste it in <span className="text-foreground">Activate cloud license</span> below.</li>
                      <li>Click Activate — the device binds and plan details appear here.</li>
                    </ol>
                    <dl className="mt-3 space-y-2 text-xs text-muted-foreground">
                      <div className="flex justify-between gap-2">
                        <dt>Plan</dt>
                        <dd className="font-mono text-foreground">{displayOrDash(lic.plan, "No plan yet")}</dd>
                      </div>
                      <div className="flex justify-between gap-2">
                        <dt>Source</dt>
                        <dd>{friendlySource(lic.source)}</dd>
                      </div>
                    </dl>
                  </div>
                )}
              </CardContent>
            </Card>
          </>
        )}

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="font-display">Activate cloud license</CardTitle>
            <CardDescription>Enter a MugoByte Platform license key to bind a device (MBT POS, Pulse, or other products).</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 sm:flex-row">
            <Input className="flex-1 font-mono" placeholder="MBT-… or PLS-…" value={key} onChange={(e) => setKey(e.target.value)} />
            <Button disabled={!key.trim() || activateMut.isPending} onClick={() => activateMut.mutate()}>
              {activateMut.isPending ? "Activating…" : "Activate"}
            </Button>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <CardTitle className="font-display">Organization licenses</CardTitle>
                <CardDescription>
                  {cloudLicenses.length} key(s) in cloud for your org — assignment, hardware lock, and seat usage.
                </CardDescription>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Button
                  size="sm"
                  variant={productFilter === "all" ? "default" : "outline"}
                  onClick={() => setProductFilter("all")}
                >
                  All ({cloudLicenses.length})
                </Button>
                {LICENSE_PRODUCTS.map((p) => (
                  <Button
                    key={p.id}
                    size="sm"
                    variant={productFilter === p.id ? "default" : "outline"}
                    onClick={() => setProductFilter(p.id)}
                  >
                    {p.name} ({productCounts[p.id] || 0})
                  </Button>
                ))}
              </div>
            </div>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            {cloudQ.isLoading ? (
              <p className="text-sm text-muted-foreground md:col-span-2">Loading licenses…</p>
            ) : filtered.length === 0 ? (
              <p className="text-sm text-muted-foreground md:col-span-2">
                {cloudLicenses.length === 0
                  ? "No cloud licenses yet. Ask an admin to issue one, or register to receive a trial."
                  : `No ${productLabel(productFilter)} licenses in this organization.`}
              </p>
            ) : filtered.map((row) => {
              const seats = `${row.activated_devices ?? 0}/${row.max_devices ?? 1}`;
              const hw = hwBindingStatus(row);
              const product = productLabel(row.product_id);
              return (
                <div key={row.id || row.license_key} className="rounded-xl border border-border/70 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <BadgeCheck className="h-4 w-4 text-primary" />
                    <span className="font-medium">{product}</span>
                    <Badge variant="secondary" className="capitalize">{row.plan}</Badge>
                    <Badge variant="outline">{row.status || "unknown"}</Badge>
                    <Badge variant={toneForState(row.claim_status || undefined)}>{claimLabel(row.claim_status)}</Badge>
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <div className="min-w-0 flex-1 truncate font-mono text-xs">{row.license_key}</div>
                    <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={() => void copyText("License key", row.license_key)}>
                      <Copy className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                  <div className="mt-2 space-y-1.5 text-xs text-muted-foreground">
                    <div className="flex items-start gap-1.5">
                      <Link2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                      <div className="min-w-0">
                        <div className="text-[10px] font-semibold uppercase tracking-wide">Assigned email</div>
                        <div className="flex items-center gap-1">
                          <span className={`truncate ${row.assigned_email ? "font-mono text-foreground" : "text-muted-foreground"}`}>
                            {row.assigned_email || "Unassigned"}
                          </span>
                          {row.assigned_email ? (
                            <Button size="sm" variant="ghost" className="h-6 w-6 p-0" onClick={() => void copyText("Email", row.assigned_email)}>
                              <Copy className="h-3 w-3" />
                            </Button>
                          ) : null}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-start gap-1.5">
                      <HardDrive className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                      <div className="min-w-0">
                        <div className="text-[10px] font-semibold uppercase tracking-wide">Hardware binding</div>
                        <div className="font-medium text-foreground">{hw.label}</div>
                        <div className="break-all font-mono text-[11px]">{hw.detail}</div>
                        {row.reserved_device_id ? (
                          <Button size="sm" variant="ghost" className="mt-0.5 h-6 px-1 text-[11px]" onClick={() => void copyText("Device ID", row.reserved_device_id)}>
                            <Copy className="mr-1 h-3 w-3" />Copy device ID
                          </Button>
                        ) : null}
                      </div>
                    </div>
                    <div className="pt-1">
                      Activation seats {seats} · expires {row.expires_at ? new Date(row.expires_at).toLocaleDateString() : "—"}
                      {row.claimed_at ? ` · claimed ${new Date(row.claimed_at).toLocaleDateString()}` : ""}
                      {row.assigned_at ? ` · assigned ${new Date(row.assigned_at).toLocaleDateString()}` : ""}
                    </div>
                  </div>
                  <Button className="mt-3" size="sm" variant="outline" onClick={() => { setKey(row.license_key || ""); }}>Use this key</Button>
                </div>
              );
            })}
          </CardContent>
        </Card>
      </div>
      {/* Fold safe-area: keep last license rows clear of browser chrome / QA bars */}
      <div className="h-8 shrink-0" aria-hidden />
    </PageShell>
  );
}

function Info({ icon, label, value, mono }: { icon: ReactNode; label: string; value: string; mono?: boolean }) {
  return <div className="rounded-xl border border-border/70 bg-muted/20 p-4"><div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground"><span className="text-primary">{icon}</span>{label}</div><div className={`mt-2 text-sm font-semibold ${mono ? "font-mono" : ""}`}>{value}</div></div>;
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return <div><div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div><div className={`mt-1 font-medium ${mono ? "font-mono" : ""}`}>{value}</div></div>;
}
