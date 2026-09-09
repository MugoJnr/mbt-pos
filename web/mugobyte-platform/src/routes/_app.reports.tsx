import { useEffect } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Boxes,
  CreditCard,
  Receipt,
  Bookmark,
} from "lucide-react";
import { PageShell } from "@/components/layout/PageShell";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { OverviewPanel } from "@/components/reports/OverviewPanel";
import { SalesPanel } from "@/components/reports/SalesPanel";
import { DebtsPanel } from "@/components/reports/DebtsPanel";
import { InventoryPanel } from "@/components/reports/InventoryPanel";
import { SavedReports } from "@/components/reports/SavedReports";
import { ShopSearch } from "@/components/reports/ShopSearch";
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
  head: () => ({ meta: [{ title: "Shop | MugoByte" }] }),
});

function Reports() {
  const { orgId, setActiveOrg, user } = useAuth();
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  const tab = search.tab || "overview";
  const defaults = defaultAnalyticsRange();
  const start = search.start || defaults.start;
  const end = search.end || defaults.end;
  const orgsQ = useQuery({ queryKey: ["platform-orgs"], queryFn: fetchOrganizations });
  const orgs = orgsQ.data || [];
  const activeOrg = orgs.find((o) => o.id === orgId) || orgs[0];

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
      <div className="mb-5 space-y-4 border-b border-border/60 pb-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              MugoByte Portal
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <h1 className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">
                Shop overview
              </h1>
              {orgs.length > 1 ? (
                <Select
                  value={activeOrg?.id || orgId || ""}
                  onValueChange={(id) => setActiveOrg(id)}
                >
                  <SelectTrigger className="h-9 w-[min(100%,16rem)] rounded-xl">
                    <SelectValue placeholder="Select shop" />
                  </SelectTrigger>
                  <SelectContent>
                    {orgs.map((org) => (
                      <SelectItem key={org.id} value={org.id}>
                        {org.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : activeOrg?.name ? (
                <span className="rounded-full border border-border/70 bg-muted/40 px-3 py-1 text-sm font-medium">
                  {activeOrg.name}
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              Signed in as {user?.full_name || user?.email || "owner"} · Kenya timezone (EAT)
            </p>
          </div>
          <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center lg:w-auto">
            {orgId ? (
              <ShopSearch
                orgId={orgId}
                className="sm:min-w-[16rem] lg:min-w-[18rem]"
                onNavigate={(nextTab) => setSearch({ tab: nextTab as AnalyticsTab })}
              />
            ) : null}
            <DateRangePicker
              start={start}
              end={end}
              onChange={(nextStart, nextEnd) => setSearch({ start: nextStart, end: nextEnd })}
            />
          </div>
        </div>
      </div>

      {!orgId ? (
        <div className="grid min-h-48 place-items-center px-4 text-center text-sm text-muted-foreground">
          <p>
            {orgsQ.isLoading
              ? "Loading your organization…"
              : "Select a business to open the shop command center."}
          </p>
        </div>
      ) : (
        <Tabs value={tab} onValueChange={(nextTab) => setSearch({ tab: nextTab as AnalyticsTab })}>
          <div className="overflow-x-auto pb-1">
            <TabsList className="h-auto min-w-max justify-start rounded-xl bg-muted/50 p-1">
              <TabsTrigger value="overview" className="rounded-lg">
                <BarChart3 className="mr-1.5 h-4 w-4" />
                Overview
              </TabsTrigger>
              <TabsTrigger value="sales" className="rounded-lg">
                <Receipt className="mr-1.5 h-4 w-4" />
                Sales
              </TabsTrigger>
              <TabsTrigger value="debts" className="rounded-lg">
                <CreditCard className="mr-1.5 h-4 w-4" />
                Debt
              </TabsTrigger>
              <TabsTrigger value="inventory" className="rounded-lg">
                <Boxes className="mr-1.5 h-4 w-4" />
                Inventory
              </TabsTrigger>
              <TabsTrigger value="saved" className="rounded-lg">
                <Bookmark className="mr-1.5 h-4 w-4" />
                Saved
              </TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="overview" className="mt-4">
            <OverviewPanel
              orgId={orgId}
              start={start}
              end={end}
              shopName={activeOrg?.name}
              onNavigateTab={(nextTab) => setSearch({ tab: nextTab as AnalyticsTab })}
            />
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
