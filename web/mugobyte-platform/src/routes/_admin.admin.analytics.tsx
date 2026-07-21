import { createFileRoute } from "@tanstack/react-router";
import { TrendingUp } from "lucide-react";
import { ModulePage } from "@/components/layout/ModulePage";

export const Route = createFileRoute("/_admin/admin/analytics")({
  component: Page,
  head: () => ({ meta: [{ title: "Platform Administration | MugoByte" }] }),
});

function Page() {
  return (
    <ModulePage
      eyebrow="Admin"
      title="Analytics"
      description="Deep insights across MugoByte Platform."
      icon={TrendingUp}
      tabs={["Overview","Cohorts","Retention","Growth"]}
      primaryAction="New View"
    />
  );
}
