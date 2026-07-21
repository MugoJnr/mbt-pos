import { createFileRoute } from "@tanstack/react-router";
import { Bell } from "lucide-react";
import { ModulePage } from "@/components/layout/ModulePage";

export const Route = createFileRoute("/_admin/admin/notifications")({
  component: Page,
  head: () => ({ meta: [{ title: "Platform Administration | MugoByte" }] }),
});

function Page() {
  return (
    <ModulePage
      eyebrow="Admin"
      title="Notifications"
      description="Announcements, incidents and platform-wide messages."
      icon={Bell}
      tabs={["All","Announcements","Incidents","Maintenance"]}
      primaryAction="New Notice"
    />
  );
}
