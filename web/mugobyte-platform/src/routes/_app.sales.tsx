import { createFileRoute } from "@tanstack/react-router";
import { Receipt } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { LiveOpsCallout } from "@/components/layout/LiveOpsCallout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const Route = createFileRoute("/_app/sales")({
  component: SalesPage,
  head: () => ({ meta: [{ title: "Sales | MugoByte" }] }),
});

function SalesPage() {
  return (
    <PageShell>
      <PageHeader
        eyebrow="MBT POS"
        title="Sales"
        description="Live receipts are served by your shop’s Live Dashboard (local POS database via Cloudflare tunnel)."
      />
      <LiveOpsCallout
        title="Open live sales"
        description="Portal accounts do not connect to local SQLite. Use the Live Dashboard on your shop tunnel for real-time sales, voids and till status."
      />
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Receipt className="h-4 w-4" /> Cloud vs Live
          </CardTitle>
          <CardDescription>
            Cloud Report Center stores scheduled/exported report history. Day-of till activity stays on the Live Dashboard.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Go to Reports for cloud report history, or Devices / License for cloud device controls.
        </CardContent>
      </Card>
    </PageShell>
  );
}
