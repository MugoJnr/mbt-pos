import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Building2, Check, Plus } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { fetchOrganizations } from "@/lib/platform";

export const Route = createFileRoute("/_app/businesses")({
  component: BusinessesPage,
  head: () => ({ meta: [{ title: "Businesses | MugoByte" }] }),
});

function BusinessesPage() {
  const { orgId, setActiveOrg } = useAuth();
  const orgsQ = useQuery({ queryKey: ["platform-orgs"], queryFn: fetchOrganizations });
  const orgs = orgsQ.data || [];

  useEffect(() => {
    if (!orgId && orgs[0]) setActiveOrg(orgs[0].id);
  }, [orgId, orgs, setActiveOrg]);

  return (
    <PageShell>
      <PageHeader
        eyebrow="Workspace"
        title="My businesses"
        description="Own or join multiple organizations. Switching a business updates cloud licenses, devices, reports and product access."
        actions={
          <Button disabled>
            <Plus className="mr-1.5 h-4 w-4" />
            Add business
          </Button>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {orgs.map((org) => {
          const active = org.id === orgId || (!orgId && org.is_primary);
          return (
            <Card
              key={org.id}
              className={`transition hover:shadow-elegant ${active ? "border-primary/50 shadow-sm" : ""}`}
            >
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="grid h-11 w-11 place-items-center rounded-xl bg-primary/10 text-primary">
                    <Building2 className="h-5 w-5" />
                  </div>
                  <div className="flex flex-wrap justify-end gap-1">
                    {org.is_primary ? <Badge variant="secondary">Primary</Badge> : null}
                    {active ? <Badge>Active</Badge> : null}
                  </div>
                </div>
                <CardTitle className="mt-3 font-display text-lg">{org.name}</CardTitle>
                <CardDescription>
                  Role: {org.role || "member"}
                  {org.slug ? ` · ${org.slug}` : ""}
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant={active ? "secondary" : "default"}
                  disabled={!!active}
                  onClick={() => setActiveOrg(org.id)}
                >
                  {active ? (
                    <>
                      <Check className="mr-1.5 h-3.5 w-3.5" /> Selected
                    </>
                  ) : (
                    "Switch to this business"
                  )}
                </Button>
                <Button asChild size="sm" variant="outline">
                  <Link to="/settings">Settings</Link>
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card className="mt-4 border-dashed">
        <CardContent className="flex flex-col items-start gap-2 p-6 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <p>
            Need another legal entity or branch group? Cloud onboarding for additional businesses will connect here.
          </p>
          <Button variant="outline" size="sm" disabled>
            Request access
          </Button>
        </CardContent>
      </Card>
    </PageShell>
  );
}
