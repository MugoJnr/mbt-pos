import { createFileRoute, redirect } from "@tanstack/react-router";
import { todayIso } from "@/components/reports/analytics";

export const Route = createFileRoute("/_app/sales")({
  beforeLoad: () => {
    const today = todayIso();
    throw redirect({ to: "/reports", search: { tab: "sales", start: today, end: today } });
  },
  head: () => ({ meta: [{ title: "Sales | MugoByte" }] }),
});
