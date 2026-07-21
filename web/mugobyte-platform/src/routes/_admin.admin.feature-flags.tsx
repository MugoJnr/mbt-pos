import { createFileRoute } from "@tanstack/react-router";
import { Sparkles } from "lucide-react";
import { ModulePage } from "@/components/layout/ModulePage";

export const Route = createFileRoute("/_admin/admin/feature-flags")({
  component: Page,
  head: () => ({ meta: [{ title: "Platform Administration | MugoByte" }] }),
});

function Page() {
  return (
    <ModulePage
      eyebrow="Admin"
      title="Feature Flags"
      description="Gate features by shop, plan or environment."
      icon={Sparkles}
      tabs={["All","Enabled","Disabled","Beta"]}
      primaryAction="New Flag"
    />
  );
}
