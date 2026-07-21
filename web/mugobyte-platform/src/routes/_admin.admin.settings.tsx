import { createFileRoute } from "@tanstack/react-router";
import { Settings } from "lucide-react";
import { ModulePage } from "@/components/layout/ModulePage";

export const Route = createFileRoute("/_admin/admin/settings")({
  component: Page,
  head: () => ({ meta: [{ title: "Platform Administration | MugoByte" }] }),
});

function Page() {
  return (
    <ModulePage
      eyebrow="Admin"
      title="System Settings"
      description="Global configuration for MugoByte Platform."
      icon={Settings}
      tabs={["General","Security","Billing","Email","Integrations"]}
      primaryAction="Save"
    />
  );
}
