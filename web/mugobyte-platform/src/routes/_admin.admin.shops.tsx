import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Building2, AlertTriangle } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getAdminOverview } from "@/lib/api";

export const Route = createFileRoute("/_admin/admin/shops")({
  component: AdminShopsPage,
  head: () => ({ meta: [{ title: "Shops | MugoByte" }] }),
});

function AdminShopsPage() {
  const overviewQ = useQuery({
    queryKey: ["admin-overview"],
    queryFn: getAdminOverview,
    retry: 1,
  });
  const data = overviewQ.data;
  const organizations = data?.organizations || [];
  const resourceErrors = Object.entries(data?.errors || {});
  const error = data?.error || (overviewQ.error as Error | null)?.message ||
    (resourceErrors.length
      ? resourceErrors.map(([resource, message]) => `${resource}: ${message}`).join(" · ")
      : "");

  return (
    <PageShell>
      <PageHeader
        eyebrow="Admin"
        title="Shops & Organisations"
        description="Every organization and linked business in the MugoByte cloud control plane."
        actions={
          <Button variant="outline" onClick={() => overviewQ.refetch()} disabled={overviewQ.isFetching}>
            <RefreshCw className={`mr-1.5 h-4 w-4 ${overviewQ.isFetching ? "animate-spin" : ""}`} />Refresh
          </Button>
        }
      />

      {error ? (
        <Card className="border-destructive/40">
          <CardContent className="flex gap-3 p-4 text-sm text-destructive">
            <AlertTriangle className="h-5 w-5 shrink-0" />
            <span>{error}</span>
          </CardContent>
        </Card>
      ) : null}

      {overviewQ.isLoading ? (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">Loading…</CardContent></Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Card><CardContent className="p-5"><div className="text-xs uppercase tracking-wide text-muted-foreground">Organizations</div><div className="mt-2 font-display text-2xl font-semibold">{organizations.length}</div><div className="mt-1 text-xs text-muted-foreground">Live cloud records</div></CardContent></Card>
            <Card><CardContent className="p-5"><div className="text-xs uppercase tracking-wide text-muted-foreground">Businesses</div><div className="mt-2 font-display text-2xl font-semibold">{data?.businesses.length || 0}</div><div className="mt-1 text-xs text-muted-foreground">Linked shop identities</div></CardContent></Card>
            <Card><CardContent className="p-5"><div className="text-xs uppercase tracking-wide text-muted-foreground">Active organizations</div><div className="mt-2 font-display text-2xl font-semibold">{organizations.filter((row) => row.status === "active").length}</div></CardContent></Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="font-display">Organization roster</CardTitle>
              <CardDescription>Plan, status and connected platform resources.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {organizations.map((org) => {
                const businesses = (data?.businesses || []).filter((row) => row.org_id === org.id);
                const licenses = (data?.licenses || []).filter((row) => row.org_id === org.id);
                const devices = (data?.devices || []).filter((row) => row.org_id === org.id);
                return (
                  <div key={org.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-border/70 p-4">
                    <div className="grid h-10 w-10 place-items-center rounded-xl bg-primary/10 text-primary">
                      <Building2 className="h-5 w-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="font-medium">{org.name}</div>
                      <div className="text-xs text-muted-foreground">{org.slug || org.id}</div>
                      {businesses.length ? <div className="mt-1 text-xs text-muted-foreground">Shops: {businesses.map((row) => row.name || "Unnamed").join(", ")}</div> : null}
                    </div>
                    <Badge variant="outline">{org.plan || "unlicensed"}</Badge>
                    <Badge variant={org.status === "active" ? "default" : "secondary"}>{org.status || "unknown"}</Badge>
                    <div className="w-full text-xs text-muted-foreground sm:w-auto">{licenses.length} licenses · {devices.length} devices</div>
                  </div>
                );
              })}
              {!error && organizations.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">No organizations are registered.</p>
              ) : null}
              {(data?.businesses || []).filter((row) => !row.org_id).map((business) => (
                <div key={business.id} className="rounded-xl border border-warning/40 p-4">
                  <div className="font-medium">{business.name || "Unnamed business"}</div>
                  <div className="mt-1 text-xs text-muted-foreground">Legacy business record is not linked to an organization.</div>
                </div>
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </PageShell>
  );
}
