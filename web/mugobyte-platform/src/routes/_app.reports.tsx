import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, FileSpreadsheet, RefreshCw } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { LiveOpsCallout } from "@/components/layout/LiveOpsCallout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { GET } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/_app/reports")({
  component: Reports,
  head: () => ({ meta: [{ title: "Reports | MugoByte" }] }),
});

type CloudReport = {
  id?: string;
  title?: string;
  report_type?: string;
  period?: string;
  created_at?: string;
  format?: string;
  status?: string;
};

function Reports() {
  const { orgId } = useAuth();
  const reportsQ = useQuery({
    queryKey: ["cloud-reports", orgId],
    queryFn: () =>
      GET<{ reports?: CloudReport[] }>("/cloud/reports", orgId ? { org_id: orgId } : undefined),
  });
  const reports = reportsQ.data?.reports || [];

  return (
    <PageShell>
      <PageHeader
        eyebrow="MBT POS"
        title="Report Center"
        description="Cloud-stored daily, weekly and monthly report history. Live shop analytics stay on Live Dashboard."
        actions={
          <Button variant="outline" onClick={() => reportsQ.refetch()}>
            <RefreshCw className="mr-1.5 h-4 w-4" />Refresh
          </Button>
        }
      />
      <LiveOpsCallout
        title="Need today’s live sales?"
        description="Interactive sales lists, payment mix and cashier filters run on your shop Live Dashboard against local SQLite."
      />
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 font-display">
            <BarChart3 className="h-4 w-4" /> Cloud report history
          </CardTitle>
          <CardDescription>
            Scheduled and emailed reports synced to Supabase. Export formats: PDF, Excel, print, email.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {reports.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No cloud reports yet. When daily/weekly jobs run, they appear here. For immediate exports use Live Dashboard → Reports.
            </p>
          ) : (
            reports.map((r, i) => (
              <div key={r.id || i} className="flex items-center justify-between gap-3 rounded-xl border border-border/70 p-3">
                <div>
                  <div className="font-semibold">{r.title || r.report_type || "Report"}</div>
                  <div className="text-xs text-muted-foreground">
                    {(r.period || "").toString()} · {(r.created_at || "").toString().slice(0, 16)}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {r.format ? <Badge variant="secondary">{r.format}</Badge> : null}
                  <FileSpreadsheet className="h-4 w-4 text-muted-foreground" />
                </div>
              </div>
            ))
          )}
          <Button asChild variant="outline">
            <Link to="/downloads">Downloads & release packages</Link>
          </Button>
        </CardContent>
      </Card>
    </PageShell>
  );
}
