import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { KeyRound } from "lucide-react";
import { PageHeader, PageShell } from "@/components/layout/PageShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { GET, POST } from "@/lib/api";

export const Route = createFileRoute("/_admin/admin/mbt-pos/password-recovery")({
  component: DeveloperEmergencyRecoveryPage,
  head: () => ({ meta: [{ title: "Developer Emergency Recovery | MBT POS" }] }),
});

type AdminRow = { id?: number; username?: string; full_name?: string; active?: boolean };
type Profile = {
  shop_name?: string;
  shop_id?: string;
  device_id?: string;
  hostname?: string;
  licence_state?: string;
  licence_plan?: string;
  superadmins?: AdminRow[];
  explanation?: string;
  portal_changes_password?: boolean;
  error?: string;
};
type Issued = {
  token?: string;
  token_id?: string;
  expires_at?: number;
  username?: string;
  note?: string;
  error?: string;
};

function DeveloperEmergencyRecoveryPage() {
  const [deviceId, setDeviceId] = useState("");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [issued, setIssued] = useState<Issued | null>(null);

  async function search() {
    setError("");
    setIssued(null);
    setProfile(null);
    setSelected(null);
    setBusy(true);
    const res = await GET<Profile>("/cloud/mbt-pos/recovery/lookup", {
      device_id: deviceId.trim(),
    });
    setBusy(false);
    if (!res || res.error) {
      setError(res?.error || "That device was not found.");
      return;
    }
    setProfile(res);
    const active = (res.superadmins || []).find((row) => row.active !== false && row.id);
    setSelected(active?.id ?? null);
  }

  async function issue() {
    if (!profile || selected == null) return;
    setError("");
    setBusy(true);
    const res = await POST<Issued>("/cloud/mbt-pos/recovery/issue", {
      device_id: profile.device_id,
      shop_id: profile.shop_id,
      user_id: selected,
      confirm: true,
    });
    setBusy(false);
    if (!res || res.error || !res.token) {
      setError(res?.error || "A recovery code was not issued.");
      return;
    }
    setIssued(res);
  }

  const admins = profile?.superadmins || [];

  return (
    <PageShell>
      <PageHeader
        eyebrow="MBT POS · Password Recovery"
        title="Developer Emergency Recovery"
        description="Issue a one-time code for an MBT POS shop. This page does not change the shop password. The till or Live Dashboard checks the code on that computer, including when it is offline."
      />

      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 font-display text-lg">
            <KeyRound className="h-4 w-4 text-primary" />
            Find the shop computer
          </CardTitle>
          <CardDescription>
            Search the real device identity, the same MBT-PC id the till already uses. Pulse and Exam Hub are not recovered here.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row">
          <Input
            aria-label="Device identity"
            value={deviceId}
            onChange={(event) => setDeviceId(event.target.value)}
            placeholder="MBT-PC-…"
            className="font-mono"
          />
          <Button type="button" onClick={() => void search()} disabled={busy || !deviceId.trim()}>
            {busy ? "Searching…" : "Search"}
          </Button>
        </CardContent>
      </Card>

      {error ? (
        <p className="mt-4 text-sm text-destructive" role="alert">{error}</p>
      ) : null}

      {profile ? (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="font-display">Confirm before generating</CardTitle>
            <CardDescription>
              {profile.explanation}
              {profile.portal_changes_password === false
                ? " A remote portal cannot reset this offline account by itself."
                : ""}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <Fact label="Shop" value={profile.shop_name || "—"} />
              <Fact label="Shop id" value={profile.shop_id || "—"} mono />
              <Fact label="Device" value={profile.device_id || "—"} mono />
              <Fact label="Computer" value={profile.hostname || "—"} />
              <Fact
                label="Licence"
                value={`${profile.licence_state || "unknown"}${profile.licence_plan ? ` · ${profile.licence_plan}` : ""}`}
              />
            </div>
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Intended Super Admin
              </div>
              {admins.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No Super Admin identity is available to bind. A code cannot be generated.
                </p>
              ) : admins.map((row) => (
                <label key={`${row.id}-${row.username}`} className="flex items-center gap-3 rounded-lg border border-border p-3 text-sm">
                  <input
                    type="radio"
                    name="superadmin"
                    checked={selected === row.id}
                    disabled={row.active === false}
                    onChange={() => setSelected(row.id ?? null)}
                  />
                  <span>
                    {row.full_name || row.username} ({row.username})
                    {row.active === false ? (
                      <Badge variant="secondary" className="ml-2">Disabled — not enabled by recovery</Badge>
                    ) : null}
                  </span>
                </label>
              ))}
            </div>
            <Button type="button" onClick={() => void issue()} disabled={busy || selected == null}>
              Generate one-time code
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {issued?.token ? (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="font-display">Code issued</CardTitle>
            <CardDescription>
              {issued.note} It expires in 30 minutes, works once, and is bound to {issued.username} on this device.
              Code id {issued.token_id}.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <p
              aria-label="Recovery code"
              className="rounded-lg border border-border bg-muted px-4 py-5 text-center font-mono text-3xl tracking-[0.28em] text-foreground"
            >
              {issued.token}
            </p>
            <p className="text-xs text-muted-foreground">
              The owner types this on the till or Live Dashboard. Reference {issued.token_id} is not a code and cannot be used again.
            </p>
          </CardContent>
        </Card>
      ) : null}
    </PageShell>
  );
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={mono ? "mt-1 break-all font-mono text-sm" : "mt-1 text-sm"}>{value}</div>
    </div>
  );
}
