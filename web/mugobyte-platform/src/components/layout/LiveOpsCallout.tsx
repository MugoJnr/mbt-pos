import { ExternalLink, Radio } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

/**
 * Portal never reads local shop SQLite. Live ops open on the shop tunnel
 * (MBT Live Dashboard) — a separate application.
 */
export function LiveOpsCallout({
  title = "Live shop data",
  description = "Sales, inventory, customers and real-time stock live on your shop’s Cloudflare Live Dashboard — not in the Portal cloud account.",
  tunnelHint,
}: {
  title?: string;
  description?: string;
  tunnelHint?: string;
}) {
  const href =
    tunnelHint ||
    (typeof window !== "undefined"
      ? localStorage.getItem("mbt_live_dashboard_url") || ""
      : "") ||
    "";

  return (
    <Card className="border-primary/25 bg-primary/5">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 font-display text-base">
          <Radio className="h-4 w-4 text-primary" />
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        {href ? (
          <Button asChild>
            <a href={href} target="_blank" rel="noreferrer">
              <ExternalLink className="mr-1.5 h-4 w-4" />
              Open Live Dashboard
            </a>
          </Button>
        ) : (
          <p className="text-sm text-muted-foreground">
            Set your shop tunnel URL in Business Settings (or open{" "}
            <code className="rounded bg-muted px-1 text-xs">https://your-shop.mugobyte.com</code>
            ) to jump straight into live operations.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
