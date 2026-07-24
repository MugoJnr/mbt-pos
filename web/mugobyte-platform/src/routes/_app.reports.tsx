import { useEffect } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BarChart3 } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { OverviewPanel } from "@/components/reports/OverviewPanel";
import { SalesPanel } from "@/components/reports/SalesPanel";
import { DebtsPanel } from "@/components/reports/DebtsPanel";
import { InventoryPanel } from "@/components/reports/InventoryPanel";
import { SavedReports } from "@/components/reports/SavedReports";
import { DateRangePicker } from "@/components/reports/ReportControls";
import {
  type AnalyticsResponse,
  type AnalyticsSearch,
  type AnalyticsTab,
  defaultAnalyticsRange,
} from "@/components/reports/analytics";
import { GET } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fetchOrganizations } from "@/lib/platform";

export const Route = createFileRoute("/_app/reports")({
  validateSearch: (search: Record<string, unknown>): AnalyticsSearch => {
    const validTabs = ["overview", "sales", "debts", "inventory", "saved"] as const;
    const tab = validTabs.includes(search.tab as (typeof validTabs)[number])
      ? (search.tab as AnalyticsTab)
      : "overview";
    const defaults = defaultAnalyticsRange();
    const start = /^\d{4}-\d{2}-\d{2}$/.test(String(search.start || ""))
      ? String(search.start)
      : defaults.start;
    const end = /^\d{4}-\d{2}-\d{2}$/.test(String(search.end || ""))
      ? String(search.end)
      : defaults.end;
    return { tab, start: start <= end ? start : end, end: start <= end ? end : start };
  },
  component: Reports,
  head: () => ({ meta: [{ title: "Reports | MugoByte" }] }),
});

function Reports() {
  const { orgId, setActiveOrg } = useAuth();
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  const tab = search.tab || "overview";
  const defaults = defaultAnalyticsRange();
  const start = search.start || defaults.start;
  const end = search.end || defaults.end;
  const orgsQ = useQuery({ queryKey: ["platform-orgs"], queryFn: fetchOrganizations });
  const orgs = orgsQ.data || [];

  useEffect(() => {
    if (!orgId && orgs[0]?.id) setActiveOrg(orgs[0].id);
  }, [orgId, orgs, setActiveOrg]);

  const filtersQ = useQuery({
    queryKey: ["cloud-analytics-filters", orgId],
    queryFn: () => GET<AnalyticsResponse>("/cloud/analytics/filters", { org_id: orgId }),
    enabled: Boolean(orgId),
  });
  const setSearch = (patch: Partial<AnalyticsSearch>) =>
    void navigate({ search: (previous) => ({ ...previous, ...patch }), replace: true });

  return (
    <PageShell>
      <PageHeader
        eyebrow="MBT POS"
        title="Cloud Analytics"
        description="Complete synced sales, debt and inventory reporting across your organization."
        actions={
          <DateRangePicker
            start={start}
            end={end}
            onChange={(nextStart, nextEnd) => setSearch({ start: nextStart, end: nextEnd })}
          />
        }
      />
      {!orgId ? (
        <div className="grid min-h-48 place-items-center px-4 text-center text-sm text-muted-foreground">
          <p>
            {orgsQ.isLoading
              ? "Loading your organization…"
              : "Select a business in the top bar to load cloud analytics."}
          </p>
        </div>
      ) : (
        <Tabs value={tab} onValueChange={(nextTab) => setSearch({ tab: nextTab as AnalyticsTab })}>
          <div className="overflow-x-auto pb-1">
            <TabsList className="h-auto min-w-max justify-start">
              <TabsTrigger value="overview">
                <BarChart3 className="mr-1.5 h-4 w-4" />
                Overview
              </TabsTrigger>
              <TabsTrigger value="sales">All Sales</TabsTrigger>
              <TabsTrigger value="debts">Debts</TabsTrigger>
              <TabsTrigger value="inventory">Inventory</TabsTrigger>
              <TabsTrigger value="saved">Saved Reports</TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="overview" className="mt-4">
            <OverviewPanel orgId={orgId} start={start} end={end} />
          </TabsContent>
          <TabsContent value="sales" className="mt-4">
            <SalesPanel orgId={orgId} start={start} end={end} filters={filtersQ.data} />
          </TabsContent>
          <TabsContent value="debts" className="mt-4">
            <DebtsPanel orgId={orgId} start={start} end={end} />
          </TabsContent>
          <TabsContent value="inventory" className="mt-4">
            <InventoryPanel orgId={orgId} start={start} end={end} filters={filtersQ.data} />
          </TabsContent>
          <TabsContent value="saved" className="mt-4">
            <SavedReports orgId={orgId} />
          </TabsContent>
        </Tabs>
      )}
    </PageShell>
  );
}
