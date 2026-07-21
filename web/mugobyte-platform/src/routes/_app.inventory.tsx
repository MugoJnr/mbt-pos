import { createFileRoute } from "@tanstack/react-router";
import { Boxes } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { LiveOpsCallout } from "@/components/layout/LiveOpsCallout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const Route = createFileRoute("/_app/inventory")({
  component: InventoryPage,
  head: () => ({ meta: [{ title: "Inventory | MugoByte" }] }),
});

function InventoryPage() {
  return (
    <PageShell>
      <PageHeader
        eyebrow="MBT POS"
        title="Inventory"
        description="Live stock levels come from the desktop POS database through your Cloudflare Live Dashboard."
      />
      <LiveOpsCallout
        title="Open live inventory"
        description="Portal never reads shop stock tables. Adjustments, low-stock and product edits stay on Live Dashboard / desktop POS."
      />
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Boxes className="h-4 w-4" /> Product marketplace
          </CardTitle>
          <CardDescription>
            Discover other MugoByte products from the launcher. Stock ops remain on Live Dashboard.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Use Launcher → My Products for Exam Hub and future apps.
        </CardContent>
      </Card>
    </PageShell>
  );
}
