import { createFileRoute } from "@tanstack/react-router";
import { CreditCard, FileText, Receipt } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/_app/billing")({
  component: BillingPage,
  head: () => ({ meta: [{ title: "Billing | MugoByte" }] }),
});

function BillingPage() {
  return (
    <PageShell>
      <PageHeader
        eyebrow="Workspace"
        title="Billing"
        description="Subscriptions, invoices and payment methods for your MugoByte products — coming soon."
        actions={<Badge variant="secondary">Soon</Badge>}
      />

      <div className="grid gap-4 lg:grid-cols-3">
        {[
          {
            icon: CreditCard,
            title: "Plans & licenses",
            desc: "Renew MBT POS seats, upgrade tiers and manage product subscriptions from one place.",
          },
          {
            icon: Receipt,
            title: "Invoices",
            desc: "Download PDF invoices and payment receipts for your organizations.",
          },
          {
            icon: FileText,
            title: "Payment methods",
            desc: "Cards, M-Pesa and bank transfer options for Kenya and regional markets.",
          },
        ].map((item) => (
          <Card key={item.title}>
            <CardHeader>
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-primary/10 text-primary">
                <item.icon className="h-5 w-5" />
              </div>
              <CardTitle className="font-display text-base">{item.title}</CardTitle>
              <CardDescription>{item.desc}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button disabled variant="outline" className="w-full">
                Coming soon
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </PageShell>
  );
}
