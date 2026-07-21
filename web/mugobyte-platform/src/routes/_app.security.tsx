import { createFileRoute } from "@tanstack/react-router";
import { Shield } from "lucide-react";
import { ModulePage } from "@/components/layout/ModulePage";

export const Route = createFileRoute("/_app/security")({
  component: () => (
    <ModulePage
      eyebrow="MBT POS"
      title="Security"
      description="Sessions, audit visibility and account protection for your cloud organization."
      icon={Shield}
      tabs={["Sessions", "Audit", "Policies"]}
    />
  ),
  head: () => ({ meta: [{ title: "Security | MugoByte" }] }),
});
