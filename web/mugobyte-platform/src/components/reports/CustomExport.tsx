import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { downloadCustomReport } from "@/lib/api";

const SECTIONS = [
  ["sales_overview", "Sales overview"],
  ["collections", "Revenue and collections"],
  ["discounts", "Discounts"],
  ["tax", "Tax"],
  ["voids", "Voided transactions"],
  ["debt", "Debt issued and collected"],
  ["outstanding", "Outstanding debt"],
  ["gross_profit", "Gross profit"],
  ["cogs", "FIFO cost of goods sold"],
  ["top_products", "Top-selling products"],
  ["categories", "Product categories"],
  ["payment_methods", "Payment methods"],
  ["staff", "Staff performance"],
  ["inventory", "Inventory and low stock"],
  ["deliveries", "Supplier deliveries"],
] as const;

export function CustomExport({ orgId, start, end }: { orgId: string; start: string; end: string }) {
  const [picked, setPicked] = useState<string[]>(["sales_overview", "collections", "outstanding"]);
  const [format, setFormat] = useState<"pdf" | "xlsx" | "csv">("pdf");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const toggle = (id: string) => {
    setPicked((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  };

  const run = async () => {
    setBusy(true);
    try {
      await downloadCustomReport({
        org_id: orgId,
        start,
        end,
        sections: picked,
        format,
        password: password || undefined,
        confirm: password ? confirm : undefined,
      });
      toast.success(
        format === "csv"
          ? "CSV downloaded. It is plain text and is not password-protected."
          : password
            ? "Protected report downloaded."
            : "Report downloaded.",
      );
      setPassword("");
      setConfirm("");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Export failed";
      if (message.startsWith("Downloaded.")) toast.message(message);
      else toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Custom export</CardTitle>
        <CardDescription>
          Only the ticked sections are included. CSV stays plain text. A password locks a PDF or Excel file and is not saved.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 sm:grid-cols-2">
          {SECTIONS.map(([id, label]) => (
            <label key={id} className="flex min-h-10 items-center gap-2 text-sm">
              <input type="checkbox" checked={picked.includes(id)} onChange={() => toggle(id)} />
              {label}
            </label>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {(["pdf", "xlsx", "csv"] as const).map((item) => (
            <Button key={item} type="button" variant={format === item ? "default" : "outline"} onClick={() => setFormat(item)}>
              {item.toUpperCase()}
            </Button>
          ))}
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <Input type="password" autoComplete="new-password" placeholder="Optional report password" value={password} onChange={(event) => setPassword(event.target.value)} aria-label="Report password" />
          <Input type="password" autoComplete="new-password" placeholder="Confirm report password" value={confirm} onChange={(event) => setConfirm(event.target.value)} aria-label="Confirm report password" />
        </div>
        <p className="text-xs text-muted-foreground">Use at least 10 characters. This is not your login password or the Super-Admin PIN.</p>
        <Button type="button" disabled={busy || !picked.length} onClick={() => void run()}>
          {busy ? "Preparing…" : "Download selected sections"}
        </Button>
      </CardContent>
    </Card>
  );
}
