import { useState } from "react";
import { Download, FileSpreadsheet, FileText, Printer } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { downloadAnalyticsExport } from "@/lib/api";

const TAB_REPORT: Record<string, string> = {
  overview: "overview",
  sales: "sales",
  debts: "debts",
  inventory: "inventory",
  saved: "overview",
};

export function ReportDownloads({
  orgId,
  shopName,
  start,
  end,
  tab,
}: {
  orgId: string;
  shopName: string;
  start: string;
  end: string;
  tab: string;
}) {
  const [busy, setBusy] = useState("");
  const report = TAB_REPORT[tab] || "sales";

  async function run(format: string, nextReport = report, print = false) {
    if (nextReport === "shop") {
      const ok = window.confirm(
        "Download a full shop report? It contains sensitive business information from the synced till.",
      );
      if (!ok) return;
    }
    setBusy(format + nextReport);
    try {
      toast.message("Preparing report...");
      await downloadAnalyticsExport({
        org_id: orgId,
        shop_name: shopName,
        start,
        end,
        report: nextReport,
        format,
        ...(print ? { print: "1" } : {}),
      });
      if (format !== "html") toast.success("Download ready");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Export failed");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" disabled={!!busy} onClick={() => void run("xlsx", "shop")}>
        <FileSpreadsheet className="mr-2 h-4 w-4" /> Full shop report
      </Button>
      <Button variant="outline" disabled={!!busy} onClick={() => void run("xlsx")}>
        <FileSpreadsheet className="mr-2 h-4 w-4" /> Excel
      </Button>
      <Button variant="outline" disabled={!!busy} onClick={() => void run("csv")}>
        <Download className="mr-2 h-4 w-4" /> CSV
      </Button>
      <Button variant="outline" disabled={!!busy} onClick={() => void run("pdf")}>
        <FileText className="mr-2 h-4 w-4" /> PDF
      </Button>
      <Button disabled={!!busy} onClick={() => void run("html", report, true)}>
        <Printer className="mr-2 h-4 w-4" /> Print
      </Button>
    </div>
  );
}
