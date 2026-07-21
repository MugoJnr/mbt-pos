import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Store, RefreshCw, Building2 } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { GET } from "@/lib/api";

export const Route = createFileRoute("/_admin/admin/shops")({
  component: AdminShopsPage,
  head: () => ({ meta: [{ title: "Shops | MugoByte" }] }),
});

type Settings = Record<string, string>;

function AdminShopsPage() {
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Settings>("/settings"),
  });
  const licQ = useQuery({
    queryKey: ["license-status"],
    queryFn: () => GET<{ state?: string; plan_name?: string; plan?: string; expiry_date?: string }>("/license/status"),
  });

  const settings = settingsQ.data || {};
  const lic = licQ.data || {};

  const org = {
    name: settings.shop_name || "Your Business",
    phone: settings.shop_phone || "—",
    address: settings.shop_address || "—",
    currency: settings.currency || "KES",
    vatRate: settings.vat_rate || "—",
    plan: lic.plan_name || lic.plan || "—",
    state: lic.state || "unknown",
    expiry: lic.expiry_date || "—",
  };

  return (
    <PageShell>
      <PageHeader
        eyebrow="Admin"
        title="Shops & Organisations"
        description="Registered businesses using this MBT POS installation. Multi-tenant support is available through the MugoByte Platform cloud service."
        actions={
          <Button variant="outline" onClick={() => { settingsQ.refetch(); licQ.refetch(); }}>
            <RefreshCw className="mr-1.5 h-4 w-4" />Refresh
          </Button>
        }
      />

      {settingsQ.isLoading ? (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">Loading…</CardContent></Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Card><CardContent className="p-5"><div className="text-xs uppercase tracking-wide text-muted-foreground">Registered shops</div><div className="mt-2 font-display text-2xl font-semibold">1</div><div className="mt-1 text-xs text-muted-foreground">This installation</div></CardContent></Card>
            <Card><CardContent className="p-5"><div className="text-xs uppercase tracking-wide text-muted-foreground">Active plan</div><div className="mt-2 font-display text-2xl font-semibold capitalize">{org.plan}</div><div className="mt-1 text-xs text-muted-foreground">Expires {org.expiry}</div></CardContent></Card>
            <Card><CardContent className="p-5"><div className="text-xs uppercase tracking-wide text-muted-foreground">License state</div><div className="mt-2"><Badge variant={org.state === "active" ? "default" : "secondary"} className="capitalize text-sm">{org.state}</Badge></div></CardContent></Card>
          </div>

          <Card>
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="grid h-12 w-12 place-items-center rounded-xl bg-primary/10 text-primary">
                  <Building2 className="h-6 w-6" />
                </div>
                <div>
                  <CardTitle className="font-display text-xl">{org.name}</CardTitle>
                  <CardDescription>Primary business on this MBT POS installation</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {[
                { label: "Business name", value: org.name },
                { label: "Phone", value: org.phone },
                { label: "Address", value: org.address },
                { label: "Currency", value: org.currency },
                { label: "VAT rate", value: `${org.vatRate}%` },
                { label: "Subscription plan", value: org.plan },
                { label: "License expiry", value: org.expiry },
              ].map(({ label, value }) => (
                <div key={label} className="rounded-xl border border-border/70 p-4">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
                  <div className="mt-1 font-medium">{value}</div>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="font-display">Multi-tenant cloud</CardTitle>
              <CardDescription>Adding multiple businesses and organisations requires the MugoByte Platform cloud service.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {[
                { title: "Multiple organisations", desc: "Create and manage separate business accounts with isolated data." },
                { title: "Branch management", desc: "Multiple locations under a single organisation with shared stock and reporting." },
                { title: "Organisation switching", desc: "Users log in once and switch between their organisations in one click." },
                { title: "Platform-wide user management", desc: "Role-based access per organisation, per application." },
              ].map((f) => (
                <div key={f.title} className="flex items-start gap-3 rounded-xl border border-border/70 p-4">
                  <Store className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div>
                    <div className="font-medium">{f.title}</div>
                    <div className="text-sm text-muted-foreground">{f.desc}</div>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </PageShell>
  );
}
