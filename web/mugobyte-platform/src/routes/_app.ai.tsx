import { createFileRoute } from "@tanstack/react-router";
import { Bot, LineChart, MessageSquare, Sparkles, TrendingUp, Warehouse } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export const Route = createFileRoute("/_app/ai")({
  component: AiHubPage,
  head: () => ({ meta: [{ title: "AI Hub | MugoByte" }] }),
});

const capabilities = [
  { icon: LineChart, title: "Business insights", desc: "Summaries of cloud sales trends and KPIs." },
  { icon: MessageSquare, title: "Ask AI", desc: "Natural-language questions about your synced data." },
  { icon: TrendingUp, title: "Forecasting", desc: "Demand and revenue projections from history." },
  { icon: Warehouse, title: "Inventory suggestions", desc: "Reorder hints based on movement patterns." },
];

function AiHubPage() {
  return (
    <PageShell>
      <PageHeader
        eyebrow="MBT POS Cloud"
        title="AI Hub"
        description="Future-ready assistants for insights, forecasting and recommendations. Grounded on cloud-synced data — never live shop SQLite."
        actions={<Badge variant="secondary">Beta</Badge>}
      />

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 font-display">
              <Bot className="h-5 w-5 text-primary" /> Ask AI
            </CardTitle>
            <CardDescription>Conversation history will sync per business once the model backend is connected.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              placeholder="e.g. Which products moved slowest last month for this business?"
              className="min-h-28 resize-none"
              disabled
            />
            <div className="flex justify-end">
              <Button disabled>
                <Sparkles className="mr-1.5 h-4 w-4" />
                Send (coming soon)
              </Button>
            </div>
            <div className="rounded-xl border border-dashed border-border/80 bg-muted/20 p-4 text-sm text-muted-foreground">
              No conversations yet. When enabled, threads appear here for the active business.
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
