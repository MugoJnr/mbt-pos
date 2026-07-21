import { createFileRoute } from "@tanstack/react-router";
import { CloudUpload } from "lucide-react";
import { ModulePage } from "@/components/layout/ModulePage";

export const Route = createFileRoute("/_admin/admin/backups")({
  component: Page,
  head: () => ({ meta: [{ title: "Platform Administration | MugoByte" }] }),
});

function Page() {
  return (
    <ModulePage
      eyebrow="Admin"
      title="Backups"
      description="Every backup across every shop and its restore status."
      icon={CloudUpload}
      tabs={["All","Recent","Failed","Restored"]}
      primaryAction="Force Backup"
    />
  );
}
