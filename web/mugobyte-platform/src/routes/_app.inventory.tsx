import { createFileRoute, redirect } from "@tanstack/react-router";
import { todayIso } from "@/components/reports/analytics";

export const Route = createFileRoute("/_app/inventory")({
  beforeLoad: () => {
    const today = todayIso();
    throw redirect({ to: "/reports", search: { tab: "inventory", start: today, end: today } });
  },
  head: () => ({ meta: [{ title: "Inventory | MugoByte" }] }),
});
