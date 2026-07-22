import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Eye, FileJson, FileSpreadsheet, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { GET } from "@/lib/api";
import { formatMoney } from "./analytics";
import { ReportState, responseError } from "./ReportState";

type Report = {
  id?: string;
  title?: string;
  report_type?: string;
  period?: string;
  period_start?: string;
  period_end?: string;
  created_at?: string;
  summary?: Record<string, unknown> | null;
  [key: string]: unknown;
};

const period = (report: Report) => report.period || [report.period_start, report.period_end].filter(Boolean).join(" → ");
const stem = (report: Report) => `mbt_${report.report_type || "report"}_${period(report).replace(/[^\w.-]+/g, "_") || "period"}`;
const escapeCsv = (value: unknown) => {
  const text = value == null ? "" : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};
const download = (name: string, body: string, type: string) => {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
};
function downloadJson(report: Report) {
  download(`${stem(report)}.json`, JSON.stringify(report, null, 2), "application/json;charset=utf-8");
}
function downloadCsv(report: Report) {
  const lines = ["section,field,value"];
  for (const [key, item] of Object.entries(report.summary || {})) {
    if (Array.isArray(item)) {
      item.forEach((row, index) => Object.entries(row as Record<string, unknown>).forEach(([field, value]) => lines.push(`${escapeCsv(key)}_${index + 1},${escapeCsv(field)},${escapeCsv(value)}`)));
    } else if (typeof item !== "object") {
      lines.push(`summary,${escapeCsv(key)},${escapeCsv(item)}`);
    }
  }
  download(`${stem(report)}.csv`, lines.join("\n"), "text/csv;charset=utf-8");
}

export function SavedReports({ orgId }: { orgId: string }) {
  const [selected, setSelected] = useState<Report | null>(null);
  const query = useQuery({
    queryKey: ["cloud-reports", orgId],
    queryFn: () => GET<{ reports?: Report[]; error?: string }>("/cloud/reports", { org_id: orgId }),
  });
  const reports = query.data?.reports || [];
  const summary = selected?.summary || {};
  const currency = String(summary.currency || "KES");
  const scalarEntries = Object.entries(summary).filter(([, item]) => !Array.isArray(item) && (typeof item !== "object" || item == null) && item != null);
  const sections = Object.entries(summary).filter(([, item]) => Array.isArray(item)) as Array<[string, Array<Record<string, unknown>>]>;
  return (
    <div className="space-y-4">
      <div className="flex justify-end"><Button variant="outline" onClick={() => void query.refetch()}><RefreshCw className="mr-2 h-4 w-4" />Refresh</Button></div>
      <ReportState loading={query.isLoading} error={responseError(query.data, query.error)} empty={!reports.length} onRetry={() => void query.refetch()}>
        <div className="space-y-3">
          {reports.map((report, index) => <Card key={report.id || index}><CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"><div><div className="flex flex-wrap items-center gap-2"><p className="font-semibold">{report.title || report.report_type || "Report"}</p>{report.report_type ? <Badge variant="secondary">{report.report_type}</Badge> : null}</div><p className="mt-1 text-xs text-muted-foreground">{period(report)}{report.created_at ? ` · saved ${new Date(report.created_at).toLocaleString()}` : ""}</p></div><div className="flex flex-wrap gap-2"><span className="self-center text-sm font-semibold">{formatMoney(report.summary?.revenue, String(report.summary?.currency || "KES"))}</span><Button size="sm" variant="outline" onClick={() => setSelected(report)}><Eye className="mr-1 h-4 w-4" />View</Button><Button size="sm" variant="outline" onClick={() => downloadCsv(report)}><FileSpreadsheet className="mr-1 h-4 w-4" />CSV</Button><Button size="sm" variant="outline" onClick={() => downloadJson(report)}><FileJson className="mr-1 h-4 w-4" />JSON</Button></div></CardContent></Card>)}
        </div>
      </ReportState>
      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-h-[92vh] max-w-5xl overflow-y-auto">
          <DialogHeader><DialogTitle>{selected?.title || selected?.report_type || "Saved report"}</DialogTitle><DialogDescription>{selected ? period(selected) : ""}</DialogDescription></DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{scalarEntries.map(([key, item]) => <div key={key} className="rounded-lg border p-3"><p className="text-xs capitalize text-muted-foreground">{key.replaceAll("_", " ")}</p><p className="mt-1 font-semibold">{typeof item === "number" && /(revenue|profit|cost|tax|discount|ticket|total)/.test(key) ? formatMoney(item, currency) : String(item)}</p></div>)}</div>
          {sections.map(([name, rows]) => rows.length ? <div key={name} className="mt-5"><h3 className="mb-2 text-sm font-semibold capitalize">{name.replaceAll("_", " ")}</h3><div className="rounded-lg border"><Table><TableHeader><TableRow>{Object.keys(rows[0]).map((key) => <TableHead key={key} className="capitalize">{key.replaceAll("_", " ")}</TableHead>)}</TableRow></TableHeader><TableBody>{rows.map((row, index) => <TableRow key={index}>{Object.keys(rows[0]).map((key) => <TableCell key={key}>{String(row[key] ?? "—")}</TableCell>)}</TableRow>)}</TableBody></Table></div></div> : null)}
          <div className="flex gap-2"><Button onClick={() => selected && downloadCsv(selected)}><FileSpreadsheet className="mr-2 h-4 w-4" />Download CSV</Button><Button variant="outline" onClick={() => selected && downloadJson(selected)}><FileJson className="mr-2 h-4 w-4" />Download JSON</Button></div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
