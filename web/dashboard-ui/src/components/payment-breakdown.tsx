import { KES } from "@/lib/format";

export type PaymentLine = {
  method?: string;
  amount?: number;
  status?: string;
  kind?: string;
  reference?: string;
};

export type SalePayments = {
  lines?: PaymentLine[];
  sale_total?: number;
  amount_tendered?: number;
  amount_collected?: number | null;
  change?: number;
  credit?: number;
  outstanding?: number | null;
  note?: string;
  warning?: string;
  consistent?: boolean;
};

function money(value: unknown) {
  if (value == null || value === "") return "—";
  return KES(Number(value));
}

function kindLabel(kind?: string) {
  if (kind === "tendered") return "Tendered";
  if (kind === "credit") return "Credit";
  if (kind === "unconfirmed") return "Not collected";
  return "Allocated";
}

export function PaymentBreakdown({ payments }: { payments?: SalePayments | null }) {
  if (!payments) return null;
  const lines = payments.lines || [];
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-text2">Payment breakdown</div>
      <div className="overflow-hidden rounded-lg border border-border">
        <div className="grid grid-cols-[1.2fr_auto_auto_auto] gap-2 border-b border-border px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-text2">
          <span>Method</span><span>Amount</span><span>Status</span><span>Recorded as</span>
        </div>
        {lines.length === 0 ? (
          <div className="px-3 py-3 text-sm text-text2">No separate payment lines are stored on this sale.</div>
        ) : lines.map((line, index) => (
          <div key={index} className="grid grid-cols-[1.2fr_auto_auto_auto] items-center gap-2 border-b border-border px-3 py-2 text-sm last:border-0">
            <div>
              <div className="font-semibold text-text">{line.method || "Payment"}</div>
              {line.reference ? <div className="text-xs text-text2">{line.reference}</div> : null}
            </div>
            <div className="font-semibold tabular-nums text-gold">{money(line.amount)}</div>
            <div className="text-text2">{line.status || "—"}</div>
            <div className="text-text2">{kindLabel(line.kind)}</div>
          </div>
        ))}
      </div>
      <div className="overflow-hidden rounded-lg border border-border text-sm">
        {[
          ["Sale total", payments.sale_total, true],
          ["Amount tendered", payments.amount_tendered, false],
          ["Amount collected", payments.amount_collected, false],
          ["Change", payments.change, false],
          ["Credit", payments.credit, false],
          ["Outstanding", payments.outstanding, false],
        ].map(([label, value, strong]) => (
          <div key={String(label)} className="flex items-center justify-between gap-3 border-b border-border px-3 py-2 last:border-0">
            <span className="text-text2">{label}</span>
            <span className={strong ? "text-base font-extrabold tabular-nums text-gold" : "font-semibold tabular-nums text-text"}>{money(value)}</span>
          </div>
        ))}
      </div>
      {payments.note ? <p className="text-sm text-text2">{payments.note}</p> : null}
      {payments.warning ? <p className="text-sm text-err">{payments.warning}</p> : null}
    </div>
  );
}
