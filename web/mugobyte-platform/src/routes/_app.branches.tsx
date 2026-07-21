import { createFileRoute } from "@tanstack/react-router";
import { Building2 } from "lucide-react";
import { ModulePage } from "@/components/layout/ModulePage";

export const Route = createFileRoute("/_app/branches")({
  component: () => (
    <ModulePage
      eyebrow="MBT POS"
      title="Branches"
      description="Locations under your organization. Live shop data remains on each shop’s Live Dashboard."
      icon={Building2}
      tabs={["Branches", "Devices"]}
      primaryAction="Add Branch"
    />
  ),
  head: () => ({ meta: [{ title: "Branches | MugoByte" }] }),
});
