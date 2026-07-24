import { createFileRoute, redirect } from "@tanstack/react-router";
import { defaultAnalyticsRange } from "@/components/reports/analytics";

export const Route = createFileRoute("/_app/sales")({
  beforeLoad: () => {
    const { start, end } = defaultAnalyticsRange();
    throw redirect({ to: "/reports", search: { tab: "sales", start, end } });
  },
  head: () => ({ meta: [{ title: "Sales | MugoByte" }] }),
});
