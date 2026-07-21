import { createFileRoute } from "@tanstack/react-router";
import { Users } from "lucide-react";
import { ModulePage } from "@/components/layout/ModulePage";

export const Route = createFileRoute("/_app/users")({
  component: () => (
    <ModulePage
      eyebrow="MBT POS"
      title="Users"
      description="Cloud organization members and roles. Desktop cashiers remain on the local POS install."
      icon={Users}
      tabs={["Members", "Invites", "Roles"]}
      primaryAction="Invite User"
    />
  ),
  head: () => ({ meta: [{ title: "Users | MugoByte" }] }),
});
