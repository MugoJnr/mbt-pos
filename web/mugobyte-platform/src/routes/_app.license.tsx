import type { ReactNode } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { KeyRound, Cpu, CalendarClock, ShieldCheck, BadgeCheck, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { GET, activateCloudLicense, listCloudLicenses, type CloudLicense } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/_app/license")({
  component: License,
  head: () => ({ meta: [{ title: "MBT POS License | MugoByte" }] }),
});

function toneForState(state?: string) {
  const s = (state || "").toLowerCase();
  if (s === "active" || s === "expiring") return "default" as const;
  if (s === "warning" || s === "critical") return "secondary" as const;
  if (s === "expired" || s === "tampered" || s === "inactive") return "destructive" as const;
  return "outline" as const;
}

function License() {
  const { orgId } = useAuth();
  const qc = useQueryClient();
  const [key, setKey] = useState("");
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

  const lic = licQ.data || {};
  const state = String(lic.state || "unknown");
  const planName = lic.plan_name || lic.plan || "—";
  const expiry = lic.expiry_date || "—";
  const device = lic.device_id || "—";
  const days = lic.days_remaining;
  const ver = versionQ.data?.version || "—";
  const cloudLicenses: CloudLicense[] = cloudQ.data?.licenses || [];

  return (
    <PageShell>
      <PageHeader
        eyebrow="MBT POS"
        title="License, Activation & Devices"
        description="Cloud licensing synchronized with the local license engine for this installation."
        actions={<Button variant="outline" onClick={() => { licQ.refetch(); cloudQ.refetch(); }}><RefreshCw className="mr-1.5 h-4 w-4" />Refresh</Button>}
      />

      {lic.error === "Forbidden" ? (
        <Card><CardContent className="p-6 text-sm text-muted-foreground">Manager or administrator access is required to view license details.</CardContent></Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="grid h-11 w-11 place-items-center rounded-xl bg-primary/10 text-primary"><ShieldCheck className="h-5 w-5" /></div>
                <div>
                  <CardTitle className="font-display">{planName}</CardTitle>
                  <CardDescription>Local engine status mirrored from MugoByte Platform when activated online.</CardDescription>
                </div>
                <div className="ml-auto"><Badge variant={toneForState(state)}>{state.toUpperCase()}</Badge></div>
              </div>
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Info icon={<CalendarClock className="h-4 w-4" />} label="Expiry" value={expiry + (days != null && days !== "" ? ` · ${days}d left` : "")} />
              <Info icon={<Cpu className="h-4 w-4" />} label="Device" value={String(device)} mono />
              <Info icon={<KeyRound className="h-4 w-4" />} label="App version" value={`v${ver}`} mono />
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="font-display">Validity</CardTitle></CardHeader>
            <CardContent className="space-y-4 text-sm">
              <Row label="Valid for use" value={lic.is_valid ? "Yes" : "No"} />
              <Row label="Activation date" value={lic.activation_date || "—"} />
              <Row label="Plan code" value={lic.plan || "—"} mono />
              <Row label="Source" value={lic.source || "—"} />
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="font-display">Activate cloud license</CardTitle>
              <CardDescription>Enter a MugoByte Platform license key to bind this device and unlock the POS.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 sm:flex-row">
              <Input className="flex-1 font-mono" placeholder="MBT-TRI-XXXX-XXXX-XXXX" value={key} onChange={(e) => setKey(e.target.value)} />
              <Button disabled={!key.trim() || activateMut.isPending} onClick={() => activateMut.mutate()}>
                {activateMut.isPending ? "Activating…" : "Activate"}
              </Button>
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="font-display">Organization licenses</CardTitle>
              <CardDescription>{cloudLicenses.length} key(s) available in cloud for your org.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-2">
              {cloudLicenses.length === 0 ? (
                <p className="text-sm text-muted-foreground md:col-span-2">No cloud licenses yet. Ask an admin to issue one, or register to receive a trial.</p>
              ) : cloudLicenses.map((row) => (
                <div key={row.id || row.license_key} className="rounded-xl border border-border/70 p-4">
                  <div className="flex items-center gap-2"><BadgeCheck className="h-4 w-4 text-primary" /><span className="font-medium capitalize">{row.plan}</span><Badge variant="outline">{row.status}</Badge></div>
                  <div className="mt-2 font-mono text-xs">{row.license_key}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{row.activated_devices ?? 0}/{row.max_devices ?? 1} devices · expires {row.expires_at ? new Date(row.expires_at).toLocaleDateString() : "—"}</div>
                  <Button className="mt-3" size="sm" variant="outline" onClick={() => { setKey(row.license_key || ""); }}>Use this key</Button>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      )}
    </PageShell>
  );
}

function Info({ icon, label, value, mono }: { icon: ReactNode; label: string; value: string; mono?: boolean }) {
  return <div className="rounded-xl border border-border/70 bg-muted/20 p-4"><div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground"><span className="text-primary">{icon}</span>{label}</div><div className={`mt-2 text-sm font-semibold ${mono ? "font-mono" : ""}`}>{value}</div></div>;
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return <div><div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div><div className={`mt-1 font-medium ${mono ? "font-mono" : ""}`}>{value}</div></div>;
}
