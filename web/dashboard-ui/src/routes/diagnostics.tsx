import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Play, Download, RotateCw, CheckCircle2, HelpCircle } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card } from "@/components/ui-kit";

export const Route = createFileRoute("/diagnostics")({
  component: Diagnostics,
});

const TABS = ["Diagnostic Log", "App Log", "Sync Queue"] as const;

const LOGS: Record<(typeof TABS)[number], string[]> = {
  "Diagnostic Log": [
    "[04:26:05] Running diagnostics…",
    "[04:26:05] DB connection: OK (sqlite 3.42, 1407 sales records)",
    "[04:26:06] Disk: 842.1 GB free of 1.0 TB",
    "[04:26:06] Log files: normal size (12.4 MB)",
    "[04:26:07] API backend: ping 218 ms",
    "[04:26:07] Printer COM3: not responding — check cable",
    "[04:26:08] Overall: WARNING",
  ],
  "App Log": [
    "[04:25:12] MBT POS started v2.3.21",
    "[04:25:14] User 'edmus' authenticated (superadmin)",
    "[04:25:18] Cache warmed — 42 categories, 1,283 products",
    "[04:25:31] Sale RCP-10421 completed (KES 1,240)",
    "[04:25:44] Telegram report sent",
  ],
  "Sync Queue": [
    "[QUEUED] sale.upload RCP-10422 attempt 1/5",
    "[QUEUED] inventory.adjust SKU=FRT-2323 delta=-4",
    "[DONE] sale.upload RCP-10420",
    "[DONE] customer.upsert Kiptoo Farms",
  ],
};

function Diagnostics() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Diagnostic Log");

  return (
    <AppShell title="Diagnostics">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-text">System Diagnostics</h2>
        <div className="flex items-center gap-2">
          <Button variant="primary">
            <Play className="h-4 w-4" /> Run Check
          </Button>
          <Button variant="secondary">
            <Download className="h-4 w-4" /> Export
          </Button>
          <Button variant="ghost">
            <RotateCw className="h-4 w-4" /> Rotate Logs
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <HealthCard label="Database" state="healthy" note="DB OK — 1407 sales records" />
        <HealthCard label="Disk Space" state="healthy" note="842.1 GB free" />
        <HealthCard label="Log Files" state="healthy" note="Log files normal" />
        <HealthCard label="Backend Process" state="unknown" note="No recent ping" />
      </div>

      <div className="text-warn font-semibold text-sm mb-4">Overall: WARNING</div>

      <Card className="overflow-hidden">
        <div className="flex border-b border-border">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`relative px-4 py-3 text-sm font-semibold ${
                tab === t ? "text-gold" : "text-text2 hover:text-text"
              }`}
            >
              {t}
              {tab === t && <span className="absolute left-3 right-3 -bottom-px h-0.5 bg-gold" />}
            </button>
          ))}
        </div>

        <pre className="font-mono text-[12.5px] leading-relaxed p-5 bg-app text-text2 min-h-[320px] whitespace-pre-wrap">
          {LOGS[tab].join("\n")}
        </pre>
      </Card>

      <div className="mt-3 text-center text-xs text-text2 font-mono">
        Platform: Windows 10 <span className="text-muted-fg mx-2">·</span> Python 3.11.9
        <span className="text-muted-fg mx-2">·</span> PID: 17956
      </div>
    </AppShell>
  );
}

function HealthCard({
  label,
  state,
  note,
}: {
  label: string;
  state: "healthy" | "warn" | "err" | "unknown";
  note: string;
}) {
  const tone =
    state === "healthy" ? "ok" : state === "warn" ? "warn" : state === "err" ? "err" : "muted";
  const text =
    state === "healthy" ? "HEALTHY" : state === "warn" ? "WARNING" : state === "err" ? "FAILING" : "UNKNOWN";
  const Icon = state === "healthy" ? CheckCircle2 : HelpCircle;
  return (
    <Card className="p-4">
      <div className="text-[10px] tracking-[0.18em] font-semibold text-text2 uppercase">
        {label}
      </div>
      <div className={`mt-2 flex items-center gap-2 text-${tone}`}>
        <Icon className="h-4 w-4" />
        <Badge tone={tone as any}>{text}</Badge>
      </div>
      <div className="mt-2 text-xs text-text2">{note}</div>
    </Card>
  );
}
