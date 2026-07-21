import { createFileRoute } from "@tanstack/react-router";
import { LifeBuoy } from "lucide-react";
import { ModulePage } from "@/components/layout/ModulePage";

export const Route = createFileRoute("/_app/support")({
  component: Page,
  head: () => ({ meta: [{ title: "Platform Administration | MugoByte" }] }),
});

function Page() {
  return (
    <ModulePage
      eyebrow="Business"
      title="Support"
      description="Knowledge base, tickets, feedback and contact."
      icon={LifeBuoy}
      tabs={["Knowledge Base","Tickets","Contact","Feedback"]}
      primaryAction="New Ticket"
    />
  );
}
