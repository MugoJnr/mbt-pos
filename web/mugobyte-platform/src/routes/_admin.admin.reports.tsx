import { createFileRoute } from "@tanstack/react-router";
import { BarChart3 } from "lucide-react";
import { ModulePage } from "@/components/layout/ModulePage";

export const Route = createFileRoute("/_admin/admin/reports")({
  component: Page,
  head: () => ({ meta: [{ title: "Platform Administration | MugoByte" }] }),
});

function Page() {
  return (
    <ModulePage
      eyebrow="Admin"
      title="Reports Center"
      description="Overall sales, active licenses, devices and revenue analytics."
      icon={BarChart3}
      tabs={["Overview","Sales","Licenses","Devices","Revenue"]}
      primaryAction="Export"
    />
  );
}
