import { createFileRoute, Link } from "@tanstack/react-router";
import { Bot, LineChart, MonitorSmartphone, Sparkles, TrendingUp, Warehouse } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/_app/ai")({
  component: AiHubPage,
  head: () => ({ meta: [{ title: "AI Hub | MugoByte" }] }),
});

const capabilities = [
  { icon: LineChart, title: "Cloud analytics", desc: "Use Reports for synced sales trends and KPIs." },
  { icon: MonitorSmartphone, title: "Desktop AI assistant", desc: "Live shop AI runs inside MBT POS on the till PC." },
  { icon: TrendingUp, title: "Forecasting", desc: "Planned — will use cloud history only when enabled." },
  { icon: Warehouse, title: "Inventory suggestions", desc: "Planned — reorder hints from synced movement." },
];

function AiHubPage() {
  return (
    <PageShell>
      <PageHeader
        eyebrow="MBT POS Cloud"
        title="AI Hub"
        description="Cloud chat is not live yet. Use Portal Reports for synced analytics, or the desktop AI assistant for live-shop help."
        actions={<Badge variant="secondary">Desktop-first</Badge>}
      />

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 font-display">
              <Bot className="h-5 w-5 text-primary" /> Where AI works today
            </CardTitle>
            <CardDescription>
              No fake send box. Portal cloud chat stays disabled until a production model backend is connected.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded-xl border border-border/80 bg-muted/20 p-4 text-sm text-muted-foreground">
              Open <strong className="text-foreground">Reports</strong> for cloud analytics, or use the
              floating AI panel inside the desktop EXE for permission-aware shop assistance.
            </div>
            <div className="flex flex-wrap gap-2">
              <Button asChild>
                <Link to="/reports">
                  <Sparkles className="mr-1.5 h-4 w-4" />
                  Open Reports
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link to="/dashboard">Back to workspace</Link>
              </Button>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-3">
          {capabilities.map((c) => (
            <Card key={c.title}>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-sm font-medium">
                  <c.icon className="h-4 w-4 text-primary" />
                  {c.title}
                </CardTitle>
                <CardDescription className="text-xs">{c.desc}</CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
      </div>
    </PageShell>
  );
}
