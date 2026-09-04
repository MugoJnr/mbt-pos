import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { GET } from "@/lib/api";

export const Route = createFileRoute("/_admin/admin/settings")({
  component: Page,
  head: () => ({ meta: [{ title: "Platform Administration | MugoByte" }] }),
});

function Page() {
  const configQ = useQuery({
    queryKey: ["cloud-config"],
    queryFn: () => GET<{
      configured?: boolean;
      enabled?: boolean;
      project_ref?: string;
      bucket?: string;
      error?: string;
    }>("/cloud/config"),
  });
  const versionQ = useQuery({
    queryKey: ["app-version"],
    queryFn: () => GET<{ version?: string; build?: string; build_date?: string }>("/version"),
  });
  const refresh = () => {
    void configQ.refetch();
    void versionQ.refetch();
  };
  const config = configQ.data;

  return (
    <PageShell>
      <PageHeader
        eyebrow="Admin"
        title="System Settings"
        description="Read-only production configuration. Secrets are intentionally never exposed in the browser."
        actions={<Button variant="outline" onClick={refresh} disabled={configQ.isFetching || versionQ.isFetching}><RefreshCw className="mr-1.5 h-4 w-4" />Refresh</Button>}
      />
      <Card>
        <CardHeader>
          <CardTitle className="font-display">Portal runtime</CardTitle>
          <CardDescription>Effective cloud and release settings reported by the backend.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {[
            ["Cloud configured", config?.configured ? "Yes" : "No"],
            ["Cloud enabled", config?.enabled ? "Yes" : "No"],
            ["Supabase project", config?.project_ref || "Not configured"],
            ["Backup bucket", config?.bucket || "mbt-backups"],
            ["Portal version", versionQ.data?.version || "Unknown"],
            ["Build", versionQ.data?.build || versionQ.data?.build_date || "Unknown"],
          ].map(([label, value]) => (
            <div key={label} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border/70 p-3">
              <span className="text-muted-foreground">{label}</span>
              <Badge variant="outline">{value}</Badge>
            </div>
          ))}
          {config?.error ? <p className="text-destructive">{config.error}</p> : null}
        </CardContent>
      </Card>
    </PageShell>
  );
}
