import { useMemo, useState, type ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  XAxis,
  YAxis,
} from "recharts";
import { Expand, Inbox } from "lucide-react";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import {
  type AnalyticsRow,
  formatMoney,
  formatNumber,
  value,
} from "./analytics";

const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-3)",
] as const;

type TrendPoint = { date: string; label: string; gross: number; transactions: number };
type MixPoint = { method: string; total: number; count: number; fill: string; key: string };

function prefersMotion() {
  return typeof window === "undefined"
    ? true
    : !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function normalizeTrend(rows: AnalyticsRow[]): TrendPoint[] {
  const points = rows
    .map((row) => {
      const raw = String(value(row, "date", "day") || "");
      const day = raw.slice(0, 10);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
      return {
        date: day,
        label: new Date(`${day}T12:00:00`).toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        }),
        gross: Number(value(row, "gross_sales", "revenue", "total") || 0),
        transactions: Number(value(row, "transactions", "count", "txns") || 0),
      };
    })
    .filter((row): row is TrendPoint => Boolean(row));
  return points.sort((a, b) => a.date.localeCompare(b.date));
}

function normalizeMix(rows: AnalyticsRow[]): MixPoint[] {
  // Pie is collected tender only — exclude zero-collected methods (e.g. unpaid credit).
  return rows
    .map((row) => ({
      method: String(value(row, "payment_method", "method") || "Unknown"),
      total: Number(value(row, "total", "amount") || 0),
      count: Number(value(row, "count", "transactions") || 0),
    }))
    .filter((row) => row.total > 0.009)
    .sort((a, b) => b.total - a.total)
    .map((row, index) => ({
      ...row,
      key: `m${index}`,
      fill: CHART_COLORS[index % CHART_COLORS.length],
    }));
}

function tickStep(length: number) {
  if (length <= 7) return 1;
  if (length <= 14) return 2;
  if (length <= 31) return 4;
  return Math.ceil(length / 8);
}

function ChartEmpty({ label }: { label: string }) {
  return (
    <div className="grid h-[240px] place-items-center rounded-xl border border-dashed border-border/70 bg-muted/20 px-4 text-center sm:h-[280px]">
      <div>
        <Inbox className="mx-auto mb-2 h-6 w-6 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}

function ClickableChartCard({
  title,
  description,
  openLabel,
  onOpen,
  children,
}: {
  title: string;
  description: string;
  openLabel: string;
  onOpen: () => void;
  children: ReactNode;
}) {
  return (
    <Card className="overflow-hidden border-border/70">
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 pb-2">
        <div className="min-w-0">
          <CardTitle className="text-base">{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        <button
          type="button"
          onClick={onOpen}
          className="inline-flex h-11 min-w-11 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-border/70 bg-background px-3 text-xs font-medium text-muted-foreground transition hover:border-primary/40 hover:bg-primary/5 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={openLabel}
        >
          <Expand className="h-4 w-4" />
          <span className="hidden sm:inline">Expand</span>
        </button>
      </CardHeader>
      <CardContent className="pt-2">
        <button
          type="button"
          onClick={onOpen}
          className={cn(
            "group relative block w-full rounded-xl text-left outline-none transition",
            "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            "hover:bg-muted/20",
          )}
          aria-label={openLabel}
        >
          <span className="pointer-events-none absolute inset-x-3 top-2 z-10 flex justify-end opacity-0 transition group-hover:opacity-100 group-focus-visible:opacity-100">
            <span className="rounded-full bg-background/90 px-2 py-0.5 text-[10px] font-medium text-muted-foreground shadow-sm">
              Open details
            </span>
          </span>
          {children}
        </button>
      </CardContent>
    </Card>
  );
}

function SalesTrendChart({
  data,
  currency,
  compact = false,
}: {
  data: TrendPoint[];
  currency: string;
  compact?: boolean;
}) {
  const config = {
    gross: { label: "Gross sales", color: "var(--chart-1)" },
  } satisfies ChartConfig;
  const step = tickStep(data.length);
  const height = compact ? "h-[240px] sm:h-[280px]" : "h-[280px] sm:h-[360px]";
  const useBars = data.length <= 3;

  if (!data.length) {
    return <ChartEmpty label="No sales trend for this period." />;
  }

  const sharedAxis = (
    <>
      <CartesianGrid vertical={false} strokeDasharray="3 3" />
      <XAxis
        dataKey="label"
        tickLine={false}
        axisLine={false}
        minTickGap={24}
        interval={0}
        tickFormatter={(_value, index) => (index % step === 0 ? String(_value) : "")}
      />
      <YAxis
        width={56}
        tickLine={false}
        axisLine={false}
        domain={[0, "auto"]}
        tickFormatter={(v) =>
          Number(v) >= 1000 ? `${Math.round(Number(v) / 100) / 10}k` : String(v)
        }
      />
      <ChartTooltip
        cursor={
          useBars
            ? { fill: "var(--muted)", opacity: 0.35 }
            : { stroke: "var(--border)", strokeDasharray: "4 4" }
        }
        content={
          <ChartTooltipContent
            formatter={(val) => formatMoney(val, currency)}
            labelFormatter={(_, payload) => {
              const point = payload?.[0]?.payload as TrendPoint | undefined;
              return point?.date || "";
            }}
          />
        }
      />
    </>
  );

  if (useBars) {
    return (
      <ChartContainer config={config} className={cn("aspect-auto w-full", height)}>
        <BarChart
          data={data}
          margin={{ left: 4, right: 8, top: 8, bottom: 0 }}
          barCategoryGap={data.length === 1 ? "55%" : "28%"}
          accessibilityLayer
        >
          {sharedAxis}
          <Bar
            dataKey="gross"
            fill="var(--color-gross)"
            radius={[10, 10, 4, 4]}
            maxBarSize={data.length === 1 ? 96 : 64}
            isAnimationActive={prefersMotion()}
          />
        </BarChart>
      </ChartContainer>
    );
  }

  return (
    <ChartContainer config={config} className={cn("aspect-auto w-full", height)}>
      <AreaChart data={data} margin={{ left: 4, right: 8, top: 8, bottom: 0 }} accessibilityLayer>
        <defs>
          <linearGradient id="salesTrendFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-gross)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--color-gross)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        {sharedAxis}
        <Area
          type="monotone"
          dataKey="gross"
          stroke="var(--color-gross)"
          strokeWidth={2.25}
          fill="url(#salesTrendFill)"
          dot={{ r: 3, strokeWidth: 2, fill: "var(--background)" }}
          activeDot={{ r: 5 }}
          isAnimationActive={prefersMotion()}
        />
      </AreaChart>
    </ChartContainer>
  );
}

function PaymentMixChart({
  data,
  currency,
  compact = false,
}: {
  data: MixPoint[];
  currency: string;
  compact?: boolean;
}) {
  const config = Object.fromEntries(
    data.map((row) => [row.key, { label: row.method, color: row.fill }]),
  ) satisfies ChartConfig;
  const height = compact ? "h-[240px] sm:h-[280px]" : "h-[280px] sm:h-[360px]";
  const total = data.reduce((sum, row) => sum + row.total, 0);

  if (!data.length) {
    return <ChartEmpty label="No collected tender for this period." />;
  }

  return (
    <div className="relative">
      {data.length === 1 ? (
        <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center pb-8 text-center">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">{data[0].method}</p>
          <p className="mt-1 font-display text-sm font-semibold tabular-nums sm:text-base">
            {formatMoney(data[0].total, currency)}
          </p>
        </div>
      ) : null}
      <ChartContainer config={config} className={cn("mx-auto aspect-auto w-full", height)}>
        <PieChart accessibilityLayer>
          <ChartTooltip
            content={
              <ChartTooltipContent
                nameKey="key"
                formatter={(val, _name, item) => {
                  const payload = item?.payload as MixPoint | undefined;
                  const pct = total ? Math.round((Number(val) / total) * 100) : 0;
                  return (
                    <div className="flex w-full items-center justify-between gap-4">
                      <span>{payload?.method || "Method"}</span>
                      <span className="font-mono tabular-nums">
                        {formatMoney(val, currency)} · {pct}%
                      </span>
                    </div>
                  );
                }}
              />
            }
          />
          <Pie
            data={data}
            dataKey="total"
            nameKey="key"
            innerRadius={compact ? 52 : 68}
            outerRadius={compact ? 84 : 110}
            strokeWidth={2}
            stroke="var(--background)"
            paddingAngle={data.length > 1 ? 2 : 0}
            isAnimationActive={prefersMotion()}
          >
            {data.map((row) => (
              <Cell key={row.key} fill={row.fill} />
            ))}
          </Pie>
          <ChartLegend content={<ChartLegendContent nameKey="key" />} />
        </PieChart>
      </ChartContainer>
    </div>
  );
}

function TrendTable({ data, currency }: { data: TrendPoint[]; currency: string }) {
  return (
    <div className="max-h-[320px] overflow-auto rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="sticky left-0 bg-background">Date</TableHead>
            <TableHead className="text-right">Transactions</TableHead>
            <TableHead className="text-right">Gross sales</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((row) => (
            <TableRow key={row.date}>
              <TableCell className="sticky left-0 bg-background font-medium">{row.date}</TableCell>
              <TableCell className="text-right">{formatNumber(row.transactions)}</TableCell>
              <TableCell className="text-right font-medium">{formatMoney(row.gross, currency)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function MixTable({ data, currency }: { data: MixPoint[]; currency: string }) {
  const total = data.reduce((sum, row) => sum + row.total, 0);
  return (
    <div className="max-h-[320px] overflow-auto rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="sticky left-0 bg-background">Method</TableHead>
            <TableHead className="text-right">Transactions</TableHead>
            <TableHead className="text-right">Collected</TableHead>
            <TableHead className="text-right">Share</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((row) => (
            <TableRow key={row.key}>
              <TableCell className="sticky left-0 bg-background font-medium">{row.method}</TableCell>
              <TableCell className="text-right">{formatNumber(row.count)}</TableCell>
              <TableCell className="text-right font-medium">{formatMoney(row.total, currency)}</TableCell>
              <TableCell className="text-right">
                {total ? `${Math.round((row.total / total) * 100)}%` : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function AnalyticsChartSection({
  trendRows,
  mixRows,
  currency = "KES",
}: {
  trendRows: AnalyticsRow[];
  mixRows: AnalyticsRow[];
  currency?: string;
}) {
  const trend = useMemo(() => normalizeTrend(trendRows), [trendRows]);
  const mix = useMemo(() => normalizeMix(mixRows), [mixRows]);
  const [open, setOpen] = useState<"trend" | "mix" | null>(null);

  return (
    <>
      <div className="grid gap-4 lg:grid-cols-[1.65fr_1fr]">
        <ClickableChartCard
          title="Sales trend"
          description="Daily gross sales for the selected range. Tap to open the full chart and table."
          openLabel="Open sales trend details"
          onOpen={() => setOpen("trend")}
        >
          <SalesTrendChart data={trend} currency={currency} compact />
        </ClickableChartCard>
        <ClickableChartCard
          title="Payment mix"
          description="Collected tender by payment method. Tap to open the full chart and table."
          openLabel="Open payment mix details"
          onOpen={() => setOpen("mix")}
        >
          <PaymentMixChart data={mix} currency={currency} compact />
        </ClickableChartCard>
      </div>

      <Dialog open={open === "trend"} onOpenChange={(next) => setOpen(next ? "trend" : null)}>
        <DialogContent className="flex max-h-[92vh] w-[min(96vw,56rem)] max-w-none flex-col gap-4 overflow-y-auto sm:rounded-2xl">
          <DialogHeader>
            <DialogTitle>Sales trend</DialogTitle>
            <DialogDescription>
              Exact daily values for this date range. Cloud analytics only — not live till data.
            </DialogDescription>
          </DialogHeader>
          <SalesTrendChart data={trend} currency={currency} />
          <TrendTable data={trend} currency={currency} />
        </DialogContent>
      </Dialog>

      <Dialog open={open === "mix"} onOpenChange={(next) => setOpen(next ? "mix" : null)}>
        <DialogContent className="flex max-h-[92vh] w-[min(96vw,48rem)] max-w-none flex-col gap-4 overflow-y-auto sm:rounded-2xl">
          <DialogHeader>
            <DialogTitle>Payment mix</DialogTitle>
            <DialogDescription>
              Collected amounts by payment method for this date range. Unpaid credit is excluded.
            </DialogDescription>
          </DialogHeader>
          <PaymentMixChart data={mix} currency={currency} />
          <MixTable data={mix} currency={currency} />
        </DialogContent>
      </Dialog>
    </>
  );
}
