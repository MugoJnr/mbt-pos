import { createFileRoute, redirect } from "@tanstack/react-router";
import { defaultAnalyticsRange } from "@/components/reports/analytics";

export const Route = createFileRoute("/_app/inventory")({
  beforeLoad: () => {
    const { start, end } = defaultAnalyticsRange();
    throw redirect({ to: "/reports", search: { tab: "inventory", start, end } });
  },
  head: () => ({ meta: [{ title: "Inventory | MugoByte" }] }),
});
