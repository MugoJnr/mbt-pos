import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, Store, Palette, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Button, Card, Input, PageHeader } from "@/components/ui-kit";
import { useTheme, type ThemeVariant } from "@/components/theme";
import { GET, POST, PUT } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DEFAULT_PREFS, loadPrefs, savePrefs, type DashboardPrefs } from "@/lib/prefs";
import { WHEEL_DEFAULTS } from "@/lib/wheel-steps";

export const Route = createFileRoute("/settings")({
  component: Settings,
});

const CURRENCIES = ["KES", "USD", "EUR", "GBP", "TZS", "UGX", "ZAR"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const PAYMENTS = [
  "Cash", "M-Pesa", "Airtel Money", "Card", "Bank Transfer",
  "Cheque", "Part Payment", "Credit Sale", "Mixed",
];
const NAV = [
  ["overview", "Overview"],
  ["shop", "Shop"],
  ["receipts", "Receipts"],
  ["mpesa", "M-Pesa"],
  ["variance", "Variance"],
  ["rounding", "Rounding"],
  ["finance", "Finance"],
  ["checkout", "Checkout"],
  ["reports", "Reports"],
  ["visuals", "Category visuals"],
  ["history", "History"],
] as const;

function darajaReadiness(url: string): string {
  const head = url.trim()
    ? "Gateway URL: saved. This is not a connection."
    : "Gateway URL: configuration incomplete.";
  return [
    head,
    "Checkout uses manual M-Pesa. STK Push is not implemented.",
    "Production is disabled.",
    "Consumer secrets and the passkey stay on the gateway, not in this browser.",
    "A health check is not a completed payment.",
  ].join("\n");
}

async function testDaraja(url: string) {
  const trimmed = url.trim().replace(/\/$/, "");
  let host = "";
  try {
    host = new URL(trimmed).hostname.toLowerCase();
  } catch {
    toast.error("Enter the lab gateway URL");
    return;
  }
  if (!host || host.includes("safaricom")) {
    toast.error("The dashboard must not call Safaricom directly");
    return;
  }
  try {
    const response = await fetch(`${trimmed}/api/v1/health`, { signal: AbortSignal.timeout(3000) });
    toast.success(`Gateway health HTTP ${response.status}. Checkout is still manual.`);
  } catch {
    toast.error("Gateway unavailable");
  }
}

function Section({
  id,
  icon,
  title,
  desc,
  children,
}: {
  id: string;
  icon: React.ReactNode;
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="p-6" as="section">
      <div id={id} className="scroll-mt-24" />
      <div className="flex items-start gap-3 mb-5">
        <div className="h-10 w-10 rounded-md grid place-items-center bg-gold/15 text-gold shrink-0">
          {icon}
        </div>
        <div>
          <h3 className="text-lg font-bold text-text leading-tight">{title}</h3>
          <p className="text-xs text-text2 mt-0.5">{desc}</p>
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">{children}</div>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-xs font-semibold text-text2 mb-1.5">{label}</div>
      {children}
    </label>
  );
}

function Check({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 min-h-11 text-sm text-text sm:col-span-2">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      className="w-full min-h-11 rounded-lg border border-border bg-input px-3 text-text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((item) => (
        <option key={item.value} value={item.value}>{item.label}</option>
      ))}
    </select>
  );
}

function printMessage(job: Record<string, string>): string {
  if (job.result === "queued") {
    return "The till queued a test page. The printer has not confirmed that paper came out.";
  }
  if (job.status === "failed" || job.result === "failed") {
    return job.detail || "The till could not queue the test page.";
  }
  return "Waiting for the till. No print has been confirmed.";
}

function flag(form: Record<string, string>, key: string, fallback = false) {
  const raw = form[key];
  if (raw == null || raw === "") return fallback;
  return raw === "1" || raw === "true";
}

function Settings() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const canSave = ["admin", "superadmin"].includes(String(user?.role || ""));
  const { theme, toggle, variant, setVariant } = useTheme();
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });
  const metaQ = useQuery({
    queryKey: ["settings-meta"],
    queryFn: () => GET<Record<string, unknown>>("/settings/meta"),
  });
  const historyQ = useQuery({
    queryKey: ["settings-history"],
    queryFn: () => GET<Array<Record<string, string>>>("/settings/history"),
    enabled: canSave,
  });
  const [form, setForm] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  const [printJob, setPrintJob] = useState<Record<string, string> | null>(null);
  const [printBusy, setPrintBusy] = useState(false);
  const visualsQ = useQuery({
    queryKey: ["category-visuals"],
    queryFn: () => GET<Record<string, unknown>>("/settings/category-visuals"),
  });
  const [visuals, setVisuals] = useState<Record<string, string | number | boolean>>({});
  const [prefs, setPrefs] = useState<DashboardPrefs>(() => loadPrefs());
  const version = Number(metaQ.data?.config_version || 0);

  useEffect(() => {
    if (settingsQ.data) {
      setForm({ ...settingsQ.data });
      setDirty(false);
    }
  }, [settingsQ.data]);

  useEffect(() => {
    if (!visualsQ.data) return;
    setVisuals({
      tile_size: Number(visualsQ.data.tile_size ?? 48),
      corner_radius: Number(visualsQ.data.corner_radius ?? 12),
      image_fit: String(visualsQ.data.image_fit ?? "cover"),
      show_labels: visualsQ.data.show_labels !== false,
      show_accent: visualsQ.data.show_accent !== false,
      compact_mode: visualsQ.data.compact_mode === true,
      default_placeholder: String(visualsQ.data.default_placeholder ?? "generic/_placeholder.svg"),
    });
  }, [visualsQ.data]);

  async function requestPrint() {
    setPrintBusy(true);
    let job = printJob;
    const waiting = job && (job.status === "pending" || job.status === "running");
    if (!waiting) {
      const created = await POST<{ success?: boolean; error?: string; command?: Record<string, string> }>(
        "/settings/device-commands",
        { command: "print_test" },
      );
      job = created?.command || null;
      if (!created?.success || !job?.id) {
        setPrintBusy(false);
        toast.error(created?.error || "The till request was not accepted.");
        return;
      }
      setPrintJob(job);
    }
    for (let attempt = 0; attempt < 8; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      const current = await GET<Record<string, string>>(`/settings/device-commands/${job.id}`);
      if (current && current.status && current.status !== "pending" && current.status !== "running") {
        setPrintJob(current);
        setPrintBusy(false);
        return;
      }
      if (current) setPrintJob(current);
    }
    setPrintBusy(false);
  }

  function saveVisuals() {
    return PUT<{ success?: boolean; error?: string }>("/settings/category-visuals", visuals);
  }

  useEffect(() => {
    const onLeave = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
    };
    window.addEventListener("beforeunload", onLeave);
    return () => window.removeEventListener("beforeunload", onLeave);
  }, [dirty]);

  const set = (key: string, value: string) => {
    setDirty(true);
    setForm((current) => ({ ...current, [key]: value }));
  };
  const setFlag = (key: string, value: boolean) => set(key, value ? "1" : "0");
  const setPref = <K extends keyof DashboardPrefs>(k: K, v: DashboardPrefs[K]) =>
    setPrefs((p) => ({ ...p, [k]: v }));

  const save = useMutation({
    mutationFn: async () => {
      savePrefs(prefs);
      const currency = (form.currency_code || form.currency_symbol || "KES").toUpperCase();
      const payload: Record<string, string> = {
        config_version: String(version),
        source: "dashboard",
        shop_name: form.shop_name || "",
        shop_address: form.shop_address || "",
        shop_phone: form.shop_phone || "",
        shop_email: form.shop_email || "",
        currency_code: currency,
        currency_symbol: currency,
        tax_rate: form.tax_rate || "0",
        receipt_footer: form.receipt_footer || "Thank you for shopping with us!",
        auto_print: form.auto_print || "0",
        printer_port: form.printer_port || "",
        mpesa_mode: "manual",
        mpesa_till: form.mpesa_till || "",
        mpesa_paybill: form.mpesa_paybill || "",
        mpesa_business_name: form.mpesa_business_name || "",
        daraja_gateway_url: (form.daraja_gateway_url || "").trim(),
        daraja_environment: "sandbox",
        variance_enabled: form.variance_enabled || "0",
        variance_enable_deposits: form.variance_enable_deposits || "0",
        variance_enable_tips: form.variance_enable_tips || "0",
        variance_enable_transport: form.variance_enable_transport || "0",
        variance_require_customer_deposit: form.variance_require_customer_deposit || "1",
        variance_allow_refund_after_finalize: "0",
        variance_max_cashier: form.variance_max_cashier || "1000",
        cash_rounding_enabled: form.cash_rounding_enabled || "1",
        cash_rounding_apply_cash: form.cash_rounding_apply_cash || "1",
        cash_rounding_apply_mpesa: form.cash_rounding_apply_mpesa || "0",
        cash_rounding_apply_card: form.cash_rounding_apply_card || "0",
        cash_rounding_apply_bank: form.cash_rounding_apply_bank || "0",
        cash_rounding_mode: form.cash_rounding_mode || "nearest",
        cash_rounding_value: form.cash_rounding_value || "5",
        receipt_tax_enabled: form.receipt_tax_enabled || "1",
        fiscal_year_start_month: form.fiscal_year_start_month || "1",
        accounting_method: form.accounting_method || "accrual",
        inventory_costing: form.inventory_costing || "weighted_avg",
        acct_cash_code: form.acct_cash_code || "1000",
        acct_mpesa_code: form.acct_mpesa_code || "1010",
        acct_bank_code: form.acct_bank_code || "1020",
        expense_category_codes: form.expense_category_codes || "6000,6100,6900",
        opening_balances_note: form.opening_balances_note || "",
        profit_use_inventory_cogs: form.profit_use_inventory_cogs || "1",
        profit_include_tips: form.profit_include_tips || "1",
        finance_use_cash_rounding: form.finance_use_cash_rounding || "1",
        after_sale_default_customer: "walk_in",
        after_sale_default_payment: form.after_sale_default_payment || "Cash",
        after_sale_focus_barcode: form.after_sale_focus_barcode || "1",
        after_sale_auto_clear_cart: form.after_sale_auto_clear_cart || "1",
        after_sale_reset_discounts: form.after_sale_reset_discounts || "1",
        after_sale_reset_notes: form.after_sale_reset_notes || "1",
        autofill_cash_paid: form.autofill_cash_paid || "1",
        autofill_product_defaults: form.autofill_product_defaults || "1",
        autofill_reports_today: form.autofill_reports_today || "1",
        autofill_clear_search_on_leave: form.autofill_clear_search_on_leave || "1",
        autofill_credit_customer_info: form.autofill_credit_customer_info || "1",
        pos_checkout_layout: form.pos_checkout_layout || "product_explorer",
        auto_report_daily: form.auto_report_daily || "0",
        auto_report_weekly: form.auto_report_weekly || "0",
        auto_db_backup: form.auto_db_backup || "0",
        wheel_pos_qty: form.wheel_pos_qty || WHEEL_DEFAULTS.wheel_pos_qty,
        wheel_stock_adjust: form.wheel_stock_adjust || WHEEL_DEFAULTS.wheel_stock_adjust,
        wheel_receive_qty: form.wheel_receive_qty || WHEEL_DEFAULTS.wheel_receive_qty,
        wheel_dashboard_qty: form.wheel_dashboard_qty || WHEEL_DEFAULTS.wheel_dashboard_qty,
      };
      const res = await PUT<{ success?: boolean; error?: string; conflict?: boolean; config_version?: number }>(
        "/settings",
        payload,
      );
      if (!res?.success) {
        const error = new Error(res?.error || "Save failed") as Error & { conflict?: boolean };
        error.conflict = Boolean(res?.conflict);
        throw error;
      }
      return res;
    },
    onSuccess: () => {
      toast.success("Settings saved");
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["settings-meta"] });
      qc.invalidateQueries({ queryKey: ["settings-history"] });
    },
    onError: (error: Error & { conflict?: boolean }) => {
      toast.error(error.message);
      if (error.conflict) qc.invalidateQueries({ queryKey: ["settings-meta"] });
    },
  });

  const variants: { id: ThemeVariant; label: string }[] = [
    { id: "default", label: "Professional" },
    { id: "mugobyte", label: "MugoByte" },
    { id: "retail", label: "Retail" },
    { id: "minimal", label: "Minimal" },
    { id: "contrast", label: "High Contrast" },
  ];
  const currency = (form.currency_code || form.currency_symbol || "KES").toUpperCase();
  const warnings = Array.isArray(metaQ.data?.warnings) ? metaQ.data?.warnings as string[] : [];
  const history = Array.isArray(historyQ.data) ? historyQ.data : [];

  return (
    <AppShell title="Settings">
      <PageHeader
        eyebrow="Admin"
        title="Settings"
        description="The same shop configuration the till uses. Appearance and dashboard layout stay on this browser."
        actions={canSave ? (
          <Button variant="primary" disabled={save.isPending || settingsQ.isLoading} onClick={() => save.mutate()}>
            <Save className="h-4 w-4" /> {save.isPending ? "Saving…" : dirty ? "Save Changes" : "Saved"}
          </Button>
        ) : undefined}
      />

      <div className="flex flex-wrap gap-2 mb-4">
        {NAV.map(([id, label]) => (
          <a key={id} href={`#${id}`} className="min-h-9 rounded-full border border-border px-3 py-1 text-xs font-semibold text-text2 hover:text-gold hover:border-gold">
            {label}
          </a>
        ))}
      </div>

      <div className="space-y-5 max-w-5xl">
        <Section id="overview" icon={<Store className="h-5 w-5" />} title="Overview" desc="What this shop is using right now">
          <Field label="Shop">
            <Input value={form.shop_name || "Not set"} readOnly />
          </Field>
          <Field label="Configuration version">
            <Input value={metaQ.data ? String(version) : "Loading…"} readOnly />
          </Field>
          <Field label="Last saved">
            <Input value={String(metaQ.data?.updated_at || "Not saved yet")} readOnly />
          </Field>
          <Field label="Saved by">
            <Input value={String(metaQ.data?.updated_by || "—")} readOnly />
          </Field>
          <p className="text-sm text-text2 sm:col-span-2">
            {dirty ? "This page has unsaved changes." : "This page matches the last loaded save."}
            {warnings.length ? ` ${warnings.join(" ")}` : ""}
          </p>
          <p className="text-sm text-text2 sm:col-span-2">
            Printer setup, sounds, Cloudflare, and cloud login stay on the till they belong to.
            Use <Link to="/backup" className="text-gold font-semibold">Backup</Link>,{" "}
            <Link to="/security" className="text-gold font-semibold">Security</Link>,{" "}
            <Link to="/void-requests" className="text-gold font-semibold">Void requests</Link>, and{" "}
            <Link to="/diagnostics" className="text-gold font-semibold">Diagnostics</Link> for those actions.
          </p>
        </Section>

        <Section id="appearance" icon={<Palette className="h-5 w-5" />} title="Appearance" desc="This browser only. It does not change the till.">
          <Field label="Mode">
            <Button variant="secondary" onClick={toggle} className="min-h-11 w-full justify-center">
              Switch to {theme === "dark" ? "Light" : "Dark"}
            </Button>
          </Field>
          <Field label="Variant">
            <div className="flex flex-wrap gap-2">
              {variants.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setVariant(item.id)}
                  className={`min-h-11 rounded-lg border px-3 text-sm font-semibold ${
                    variant === item.id ? "border-gold bg-gold/15 text-gold" : "border-border bg-card text-text2"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </Field>
        </Section>

        <Section id="browser" icon={<SlidersHorizontal className="h-5 w-5" />} title="Dashboard preferences" desc="Saved in this browser, not in the shop database">
          <Field label={`Refresh interval (${prefs.refreshIntervalSec}s)`}>
            <input type="range" min={15} max={120} step={5} value={prefs.refreshIntervalSec}
              onChange={(e) => setPref("refreshIntervalSec", Number(e.target.value))}
              className="w-full accent-[var(--gold)] min-h-11" />
          </Field>
          <Field label="Table density">
            <Select value={prefs.tableDensity} onChange={(v) => setPref("tableDensity", v as DashboardPrefs["tableDensity"])}
              options={[{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }]} />
          </Field>
          <Field label="Layout">
            <Select value={prefs.layout} onChange={(v) => setPref("layout", v as DashboardPrefs["layout"])}
              options={[{ value: "auto", label: "Auto" }, { value: "dense", label: "Dense" }, { value: "relaxed", label: "Relaxed" }]} />
          </Field>
          <Field label="Export format">
            <Select value={prefs.exportFormat} onChange={(v) => setPref("exportFormat", v as DashboardPrefs["exportFormat"])}
              options={[{ value: "csv", label: "CSV" }, { value: "xlsx", label: "Excel (XLSX)" }]} />
          </Field>
        </Section>

        {!canSave ? (
          <p className="text-sm text-text2">You can read shop settings. Only an administrator can save them.</p>
        ) : null}

        <fieldset disabled={!canSave} className="space-y-5 border-0 p-0 m-0 min-w-0">
          <Section id="shop" icon={<Store className="h-5 w-5" />} title="Shop Information" desc="Shown on receipts and reports. Currency and tax are set in Finance.">
            <Field label="Shop name">
              <Input value={form.shop_name || ""} onChange={(e) => set("shop_name", e.target.value)} />
            </Field>
            <Field label="Phone">
              <Input value={form.shop_phone || ""} onChange={(e) => set("shop_phone", e.target.value)} />
            </Field>
            <Field label="Email">
              <Input value={form.shop_email || ""} onChange={(e) => set("shop_email", e.target.value)} />
            </Field>
            <Field label="Address">
              <Input value={form.shop_address || ""} onChange={(e) => set("shop_address", e.target.value)} />
            </Field>
            <Field label="Currency in use">
              <Input value={currency} readOnly />
            </Field>
            <Field label="Tax rate in use">
              <Input value={form.tax_rate || "0.0"} readOnly />
            </Field>
          </Section>

          <Section id="receipts" icon={<Store className="h-5 w-5" />} title="Receipt Printing" desc="The printer port belongs to this shop computer">
            <Field label="Receipt footer">
              <Input value={form.receipt_footer || ""} placeholder="Thank you for shopping with us!"
                onChange={(e) => set("receipt_footer", e.target.value)} />
            </Field>
            <Field label="Printer port">
              <Input value={form.printer_port || ""} placeholder="USB, COM3, or /dev/usb/lp0"
                onChange={(e) => set("printer_port", e.target.value)} />
            </Field>
            <Check label="Auto-print receipt after each sale" checked={flag(form, "auto_print")}
              onChange={(v) => setFlag("auto_print", v)} />
            <p className="text-sm text-text2 sm:col-span-2">
              A test page is queued on the till. The printer does not confirm that paper came out.
              {printJob ? ` ${printMessage(printJob)}` : ""}
            </p>
            {canSave ? (
              <Button type="button" variant="secondary" disabled={printBusy} onClick={() => void requestPrint()}>
                {printBusy
                  ? "Waiting for the till…"
                  : printJob && (printJob.status === "pending" || printJob.status === "running")
                    ? "Check the till's answer"
                    : "Ask the till to print a test page"}
              </Button>
            ) : null}
          </Section>

          <Section id="mpesa" icon={<Store className="h-5 w-5" />} title="M-Pesa Payments" desc="Printed on the receipt. This does not take the payment.">
            <Field label="Till number">
              <Input value={form.mpesa_till || ""} onChange={(e) => set("mpesa_till", e.target.value)} />
            </Field>
            <Field label="Paybill (optional)">
              <Input value={form.mpesa_paybill || ""} onChange={(e) => set("mpesa_paybill", e.target.value)} />
            </Field>
            <Field label="Business name">
              <Input value={form.mpesa_business_name || ""} onChange={(e) => set("mpesa_business_name", e.target.value)} />
            </Field>
            <Field label="Gateway URL">
              <Input value={form.daraja_gateway_url || ""} placeholder="http://127.0.0.1:8080"
                onChange={(e) => set("daraja_gateway_url", e.target.value)} />
            </Field>
            <Field label="Environment">
              <Input value="Sandbox (production disabled)" readOnly />
            </Field>
            <p className="text-sm text-text2 whitespace-pre-line sm:col-span-2">{darajaReadiness(form.daraja_gateway_url || "")}</p>
            <Button type="button" variant="secondary" onClick={() => void testDaraja(form.daraja_gateway_url || "")}>
              Test gateway health
            </Button>
          </Section>

          <Section id="variance" icon={<SlidersHorizontal className="h-5 w-5" />} title="Payment Variance" desc="What a cashier may do with money paid above the sale total">
            <Check label="Enable payment variance on Till / M-Pesa" checked={flag(form, "variance_enabled")} onChange={(v) => setFlag("variance_enabled", v)} />
            <Check label="Allow customer deposit / advance" checked={flag(form, "variance_enable_deposits")} onChange={(v) => setFlag("variance_enable_deposits", v)} />
            <Check label="Allow tip" checked={flag(form, "variance_enable_tips")} onChange={(v) => setFlag("variance_enable_tips", v)} />
            <Check label="Allow transport / delivery fee" checked={flag(form, "variance_enable_transport")} onChange={(v) => setFlag("variance_enable_transport", v)} />
            <Check label="Require a customer for deposits and advances" checked={flag(form, "variance_require_customer_deposit", true)} onChange={(v) => setFlag("variance_require_customer_deposit", v)} />
            <Field label="Max cashier-approvable variance">
              <Input type="number" min={0} step="0.01" value={form.variance_max_cashier || "1000"}
                onChange={(e) => set("variance_max_cashier", e.target.value)} />
            </Field>
            <p className="text-sm text-text2 sm:col-span-2">Amounts above that limit need a manager or the Super-Admin PIN. Refunding excess after the sale is finalized stays off. Tips and transport are not product sales.</p>
          </Section>

          <Section id="rounding" icon={<SlidersHorizontal className="h-5 w-5" />} title="Cash Rounding" desc="Rounds the amount due. Product prices stay as entered.">
            <Check label="Enable cash rounding" checked={flag(form, "cash_rounding_enabled", true)} onChange={(v) => setFlag("cash_rounding_enabled", v)} />
            <Check label="Apply to Cash" checked={flag(form, "cash_rounding_apply_cash", true)} onChange={(v) => setFlag("cash_rounding_apply_cash", v)} />
            <Check label="Apply to M-Pesa (not recommended)" checked={flag(form, "cash_rounding_apply_mpesa")} onChange={(v) => setFlag("cash_rounding_apply_mpesa", v)} />
            <Check label="Apply to Card" checked={flag(form, "cash_rounding_apply_card")} onChange={(v) => setFlag("cash_rounding_apply_card", v)} />
            <Check label="Apply to Bank / Cheque / Transfer" checked={flag(form, "cash_rounding_apply_bank")} onChange={(v) => setFlag("cash_rounding_apply_bank", v)} />
            <Field label="Rounding mode">
              <Select value={form.cash_rounding_mode || "nearest"} onChange={(v) => set("cash_rounding_mode", v)} options={[
                ["nearest", "Nearest"], ["none", "No Rounding"], ["nearest_1", "Nearest 1"],
                ["nearest_5", "Nearest 5"], ["nearest_10", "Nearest 10"],
                ["always_up", "Always Up"], ["always_down", "Always Down"],
              ].map(([value, label]) => ({ value, label }))} />
            </Field>
            <Field label="Rounding value (KSh 1–1000)">
              <Input type="number" min={1} max={1000} value={form.cash_rounding_value || "5"}
                onChange={(e) => set("cash_rounding_value", e.target.value)} />
            </Field>
          </Section>

          <Section id="finance" icon={<Store className="h-5 w-5" />} title="Finance" desc="Currency and tax here replace the shop copies. Past sales are not rewritten.">
            <Field label="Currency">
              <Select value={CURRENCIES.includes(currency) ? currency : "KES"} onChange={(v) => {
                set("currency_code", v);
                set("currency_symbol", v);
              }} options={CURRENCIES.map((code) => ({ value: code, label: code }))} />
            </Field>
            <Field label="Tax rate (%)">
              <Input type="number" min={0} max={100} step="0.1" value={form.tax_rate || "0"}
                onChange={(e) => set("tax_rate", e.target.value)} />
            </Field>
            <Check label="Show tax line on receipts" checked={flag(form, "receipt_tax_enabled", true)} onChange={(v) => setFlag("receipt_tax_enabled", v)} />
            <Field label="Fiscal year starts">
              <Select value={form.fiscal_year_start_month || "1"} onChange={(v) => set("fiscal_year_start_month", v)}
                options={MONTHS.map((name, index) => ({ value: String(index + 1), label: name }))} />
            </Field>
            <Field label="Accounting method">
              <Select value={form.accounting_method || "accrual"} onChange={(v) => set("accounting_method", v)}
                options={[{ value: "accrual", label: "Accrual (recommended)" }, { value: "cash", label: "Cash basis" }]} />
            </Field>
            <Field label="Inventory costing">
              <Select value={form.inventory_costing || "weighted_avg"} onChange={(v) => set("inventory_costing", v)}
                options={[{ value: "weighted_avg", label: "Weighted average cost" }, { value: "fifo", label: "FIFO" }]} />
            </Field>
            <Field label="Cash account"><Input value={form.acct_cash_code || "1000"} onChange={(e) => set("acct_cash_code", e.target.value)} /></Field>
            <Field label="M-Pesa account"><Input value={form.acct_mpesa_code || "1010"} onChange={(e) => set("acct_mpesa_code", e.target.value)} /></Field>
            <Field label="Bank account"><Input value={form.acct_bank_code || "1020"} onChange={(e) => set("acct_bank_code", e.target.value)} /></Field>
            <Field label="Expense category codes">
              <Input value={form.expense_category_codes || "6000,6100,6900"} onChange={(e) => set("expense_category_codes", e.target.value)} />
            </Field>
            <Field label="Opening balances note">
              <Input value={form.opening_balances_note || ""} onChange={(e) => set("opening_balances_note", e.target.value)} />
            </Field>
            <Check label="Gross profit uses inventory cost from sales" checked={flag(form, "profit_use_inventory_cogs", true)} onChange={(v) => setFlag("profit_use_inventory_cogs", v)} />
            <Check label="Include tips and transport in net profit" checked={flag(form, "profit_include_tips", true)} onChange={(v) => setFlag("profit_include_tips", v)} />
            <Check label="Use the cash rounding rules above" checked={flag(form, "finance_use_cash_rounding", true)} onChange={(v) => setFlag("finance_use_cash_rounding", v)} />
            <p className="text-sm sm:col-span-2"><Link to="/finance" className="text-gold font-semibold">Open Finance</Link></p>
          </Section>

          <Section id="checkout" icon={<SlidersHorizontal className="h-5 w-5" />} title="POS Checkout" desc="Applied on the till after the next successful save">
            <Field label="Checkout layout">
              <Select value={form.pos_checkout_layout || "product_explorer"} onChange={(v) => set("pos_checkout_layout", v)} options={[
                { value: "retail_classic", label: "Retail Classic" },
                { value: "product_explorer", label: "Product Explorer" },
                { value: "checkout_pro", label: "Checkout Pro" },
              ]} />
            </Field>
            <Field label="Default customer"><Input value="Walk-in Customer" readOnly /></Field>
            <Field label="Default payment">
              <Select value={form.after_sale_default_payment || "Cash"} onChange={(v) => set("after_sale_default_payment", v)}
                options={PAYMENTS.map((name) => ({ value: name, label: name }))} />
            </Field>
            <Check label="Focus barcode / search after each sale" checked={flag(form, "after_sale_focus_barcode", true)} onChange={(v) => setFlag("after_sale_focus_barcode", v)} />
            <Check label="Auto-clear cart after a successful sale" checked={flag(form, "after_sale_auto_clear_cart", true)} onChange={(v) => setFlag("after_sale_auto_clear_cart", v)} />
            <Check label="Reset discounts after sale" checked={flag(form, "after_sale_reset_discounts", true)} onChange={(v) => setFlag("after_sale_reset_discounts", v)} />
            <Check label="Reset notes after sale" checked={flag(form, "after_sale_reset_notes", true)} onChange={(v) => setFlag("after_sale_reset_notes", v)} />
            <Check label="Auto-fill Cash Paid to the amount due" checked={flag(form, "autofill_cash_paid", true)} onChange={(v) => setFlag("autofill_cash_paid", v)} />
            <Check label="Product create defaults (unit, minimum stock, Active)" checked={flag(form, "autofill_product_defaults", true)} onChange={(v) => setFlag("autofill_product_defaults", v)} />
            <Check label="Reports open on Today" checked={flag(form, "autofill_reports_today", true)} onChange={(v) => setFlag("autofill_reports_today", v)} />
            <Check label="Clear module search when leaving a tab" checked={flag(form, "autofill_clear_search_on_leave", true)} onChange={(v) => setFlag("autofill_clear_search_on_leave", v)} />
            <Check label="Show credit balance and limit when a customer is selected" checked={flag(form, "autofill_credit_customer_info", true)} onChange={(v) => setFlag("autofill_credit_customer_info", v)} />
          </Section>

          <Section id="reports" icon={<Store className="h-5 w-5" />} title="Automatic Reports" desc="Delivered through the shop notification path configured on the till">
            <Check label="Send a daily sales report" checked={flag(form, "auto_report_daily")} onChange={(v) => setFlag("auto_report_daily", v)} />
            <Check label="Also send a weekly summary (last 7 days)" checked={flag(form, "auto_report_weekly")} onChange={(v) => setFlag("auto_report_weekly", v)} />
            <Check label="Automatic database backup" checked={flag(form, "auto_db_backup")} onChange={(v) => setFlag("auto_db_backup", v)} />
            <p className="text-sm sm:col-span-2"><Link to="/backup" className="text-gold font-semibold">Open Backup Center</Link> to run or inspect a backup on this computer.</p>
          </Section>

          <Section id="wheels" icon={<SlidersHorizontal className="h-5 w-5" />} title="Numeric mouse-wheel steps" desc="How far one wheel notch moves a focused quantity">
            <Field label="POS sale quantity">
              <Input type="number" min={0.001} step="0.001" value={form.wheel_pos_qty || WHEEL_DEFAULTS.wheel_pos_qty} onChange={(e) => set("wheel_pos_qty", e.target.value)} />
            </Field>
            <Field label="Inventory adjustment">
              <Input type="number" min={0.001} step="0.001" value={form.wheel_stock_adjust || WHEEL_DEFAULTS.wheel_stock_adjust} onChange={(e) => set("wheel_stock_adjust", e.target.value)} />
            </Field>
            <Field label="Supplier receiving">
              <Input type="number" min={0.001} step="0.001" value={form.wheel_receive_qty || WHEEL_DEFAULTS.wheel_receive_qty} onChange={(e) => set("wheel_receive_qty", e.target.value)} />
            </Field>
            <Field label="General dashboard quantity">
              <Input type="number" min={0.001} step="0.001" value={form.wheel_dashboard_qty || WHEEL_DEFAULTS.wheel_dashboard_qty} onChange={(e) => set("wheel_dashboard_qty", e.target.value)} />
            </Field>
          </Section>
        </fieldset>

          <Section id="visuals" icon={<Palette className="h-5 w-5" />} title="Category visuals" desc="The same tile preferences the till uses. Built-in icons stay on this computer.">
            <Field label="Tile size (32–128)">
              <Input type="number" min={32} max={128} value={String(visuals.tile_size ?? 48)}
                onChange={(e) => setVisuals((current) => ({ ...current, tile_size: Number(e.target.value) }))} />
            </Field>
            <Field label="Corner radius (0–32)">
              <Input type="number" min={0} max={32} value={String(visuals.corner_radius ?? 12)}
                onChange={(e) => setVisuals((current) => ({ ...current, corner_radius: Number(e.target.value) }))} />
            </Field>
            <Field label="Image fit">
              <Select value={String(visuals.image_fit ?? "cover")} onChange={(v) => setVisuals((current) => ({ ...current, image_fit: v }))}
                options={[{ value: "cover", label: "Cover" }, { value: "contain", label: "Contain" }]} />
            </Field>
            <Field label="Placeholder">
              <Input value={String(visuals.default_placeholder ?? "")}
                onChange={(e) => setVisuals((current) => ({ ...current, default_placeholder: e.target.value }))} />
            </Field>
            <Check label="Show labels" checked={Boolean(visuals.show_labels)} onChange={(v) => setVisuals((c) => ({ ...c, show_labels: v }))} />
            <Check label="Show accent ring" checked={Boolean(visuals.show_accent)} onChange={(v) => setVisuals((c) => ({ ...c, show_accent: v }))} />
            <Check label="Compact mode" checked={Boolean(visuals.compact_mode)} onChange={(v) => setVisuals((c) => ({ ...c, compact_mode: v }))} />
            {canSave ? (
              <Button type="button" variant="secondary" onClick={() => {
                void saveVisuals().then((res) => {
                  if (!res?.success) toast.error(res?.error || "Category visuals were not saved.");
                  else {
                    toast.success("Category visuals saved");
                    qc.invalidateQueries({ queryKey: ["category-visuals"] });
                  }
                });
              }}>Save category visuals</Button>
            ) : null}
          </Section>

          <Section id="history" icon={<Store className="h-5 w-5" />} title="Settings change history" desc="Passwords, PINs, and tokens are never listed">
          {!canSave ? (
            <p className="text-sm text-text2 sm:col-span-2">An administrator can open the change history.</p>
          ) : history.length === 0 ? (
            <p className="text-sm text-text2 sm:col-span-2">{historyQ.isLoading ? "Loading history…" : "No settings changes have been recorded yet."}</p>
          ) : (
            <div className="sm:col-span-2 overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead>
                  <tr className="text-text2">
                    <th className="py-2 pr-3">When</th>
                    <th className="py-2 pr-3">Setting</th>
                    <th className="py-2 pr-3">From</th>
                    <th className="py-2 pr-3">To</th>
                    <th className="py-2 pr-3">User</th>
                    <th className="py-2">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {history.slice(0, 40).map((row) => (
                    <tr key={row.id} className="border-t border-border">
                      <td className="py-2 pr-3 whitespace-nowrap">{row.created_at}</td>
                      <td className="py-2 pr-3">{row.setting_key}</td>
                      <td className="py-2 pr-3">{row.old_value}</td>
                      <td className="py-2 pr-3">{row.new_value}</td>
                      <td className="py-2 pr-3">{row.username}</td>
                      <td className="py-2">{row.result}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
        <p className="text-center text-xs text-text2">MBT POS · MugoByte Technologies · mugobyte.com</p>
      </div>
    </AppShell>
  );
}
