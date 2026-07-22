import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, Store, MessageSquare, Palette, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Button, Card, Input, PageHeader } from "@/components/ui-kit";
import { useTheme, type ThemeVariant } from "@/components/theme";
import { GET, PUT } from "@/lib/api";
import {
  DEFAULT_PREFS,
  loadPrefs,
  savePrefs,
  type DashboardPrefs,
} from "@/lib/prefs";

export const Route = createFileRoute("/settings")({
  component: Settings,
});

function Section({
  icon,
  title,
  desc,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="p-6">
      <div className="flex items-start gap-3 mb-5">
        <div className="h-10 w-10 rounded-md grid place-items-center bg-gold/15 text-gold shrink-0">
          {icon}
        </div>
        <div>
          <div className="text-[10px] tracking-[0.18em] font-semibold text-gold uppercase">
            Section
          </div>
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

function Settings() {
  const qc = useQueryClient();
  const { theme, toggle, variant, setVariant } = useTheme();
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });
  const [form, setForm] = useState<Record<string, string>>({});
  const [prefs, setPrefs] = useState<DashboardPrefs>(() => loadPrefs());

  useEffect(() => {
    if (settingsQ.data) setForm({ ...settingsQ.data });
  }, [settingsQ.data]);

  const save = useMutation({
    mutationFn: async () => {
      savePrefs(prefs);
      const payload = {
        shop_name: form.shop_name || "",
        shop_phone: form.shop_phone || "",
        shop_email: form.shop_email || "",
        shop_address: form.shop_address || "",
        receipt_footer: form.receipt_footer || "",
        currency_symbol: form.currency_symbol || "KES",
        tax_rate: form.tax_rate || "0",
      };
      const res = await PUT<{ success?: boolean; error?: string }>("/settings", payload);
      if (!res?.success) throw new Error(res?.error || "Save failed");
      return res;
    },
    onSuccess: () => {
      toast.success("Settings saved");
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));
  const setPref = <K extends keyof DashboardPrefs>(k: K, v: DashboardPrefs[K]) =>
    setPrefs((p) => ({ ...p, [k]: v }));

  const variants: { id: ThemeVariant; label: string }[] = [
    { id: "default", label: "Professional" },
    { id: "mugobyte", label: "MugoByte" },
    { id: "retail", label: "Retail" },
    { id: "minimal", label: "Minimal" },
    { id: "contrast", label: "High Contrast" },
  ];

  return (
    <AppShell title="Settings">
      <PageHeader
        eyebrow="Admin"
        title="Settings"
        description="Configure your shop, receipts, appearance, dashboard layout, and integrations."
        actions={
          <Button
            variant="primary"
            disabled={save.isPending || settingsQ.isLoading}
            onClick={() => save.mutate()}
          >
            <Save className="h-4 w-4" /> {save.isPending ? "Saving…" : "Save Changes"}
          </Button>
        }
      />

      <div className="space-y-5 max-w-5xl">
        <Section
          icon={<Palette className="h-5 w-5" />}
          title="Appearance"
          desc="Theme mode and visual variant (presentation only)"
        >
          <Field label="Mode">
            <Button variant="secondary" onClick={toggle} className="min-h-11 w-full justify-center">
              Switch to {theme === "dark" ? "Light" : "Dark"}
            </Button>
          </Field>
          <Field label="Variant">
            <div className="flex flex-wrap gap-2">
              {variants.map((v) => (
                <button
                  key={v.id}
                  type="button"
                  onClick={() => setVariant(v.id)}
                  className={`min-h-11 rounded-lg border px-3 text-sm font-semibold transition-colors ${
                    variant === v.id
                      ? "border-gold bg-gold/15 text-gold"
                      : "border-border bg-card text-text2 hover:bg-hover"
                  }`}
                >
                  {v.label}
                </button>
              ))}
            </div>
          </Field>
        </Section>

        <Section
          icon={<SlidersHorizontal className="h-5 w-5" />}
          title="Dashboard preferences"
          desc="Refresh, widgets, density, language & exports — saved on this device"
        >
          <Field label={`Refresh interval (${prefs.refreshIntervalSec}s)`}>
            <input
              type="range"
              min={15}
              max={120}
              step={5}
              value={prefs.refreshIntervalSec}
              onChange={(e) => setPref("refreshIntervalSec", Number(e.target.value))}
              className="w-full accent-[var(--gold)] min-h-11"
            />
          </Field>
          <Field label="Table density">
            <select
              className="w-full min-h-11 rounded-lg border border-border bg-input px-3 text-text"
              value={prefs.tableDensity}
              onChange={(e) => setPref("tableDensity", e.target.value as any)}
            >
              <option value="comfortable">Comfortable</option>
              <option value="compact">Compact</option>
            </select>
          </Field>
          <Field label="Layout">
            <select
              className="w-full min-h-11 rounded-lg border border-border bg-input px-3 text-text"
              value={prefs.layout}
              onChange={(e) => setPref("layout", e.target.value as any)}
            >
              <option value="auto">Auto</option>
              <option value="dense">Dense</option>
              <option value="relaxed">Relaxed</option>
            </select>
          </Field>
          <Field label="Language">
            <select
              className="w-full min-h-11 rounded-lg border border-border bg-input px-3 text-text"
              value={prefs.language}
              onChange={(e) => setPref("language", e.target.value as any)}
            >
              <option value="en">English</option>
              <option value="sw">Kiswahili (labels later)</option>
            </select>
          </Field>
          <Field label="Export format">
            <select
              className="w-full min-h-11 rounded-lg border border-border bg-input px-3 text-text"
              value={prefs.exportFormat}
              onChange={(e) => setPref("exportFormat", e.target.value as any)}
            >
              <option value="csv">CSV</option>
              <option value="xlsx">Excel (XLSX)</option>
            </select>
          </Field>
          <Field label="Toggles">
            <div className="flex flex-col gap-2 text-sm text-text">
              {(
                [
                  ["notificationsEnabled", "Desktop notifications feed"],
                  ["showCharts", "Show charts"],
                  ["showWidgets", "Show insight widgets"],
                ] as const
              ).map(([key, label]) => (
                <label key={key} className="inline-flex items-center gap-2 min-h-11">
                  <input
                    type="checkbox"
                    checked={Boolean(prefs[key])}
                    onChange={(e) => setPref(key, e.target.checked as any)}
                  />
                  {label}
                </label>
              ))}
            </div>
          </Field>
          <Field label="Widget visibility">
            <div className="flex flex-wrap gap-2">
              {(
                Object.keys(DEFAULT_PREFS.widgets) as (keyof DashboardPrefs["widgets"])[]
              ).map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() =>
                    setPrefs((p) => ({
                      ...p,
                      widgets: { ...p.widgets, [key]: !p.widgets[key] },
                    }))
                  }
                  className={`min-h-11 rounded-lg border px-3 text-sm font-semibold ${
                    prefs.widgets[key]
                      ? "border-gold bg-gold/15 text-gold"
                      : "border-border bg-card text-text2"
                  }`}
                >
                  {key}
                </button>
              ))}
            </div>
          </Field>
        </Section>

        <Section
          icon={<Store className="h-5 w-5" />}
          title="Shop Information"
          desc="Displayed on receipts and reports"
        >
          <Field label="Shop Name">
            <Input value={form.shop_name || ""} onChange={(e) => set("shop_name", e.target.value)} />
          </Field>
          <Field label="Phone">
            <Input
              value={form.shop_phone || ""}
              onChange={(e) => set("shop_phone", e.target.value)}
            />
          </Field>
          <Field label="Email">
            <Input
              value={form.shop_email || ""}
              onChange={(e) => set("shop_email", e.target.value)}
            />
          </Field>
          <Field label="Address">
            <Input
              value={form.shop_address || ""}
              onChange={(e) => set("shop_address", e.target.value)}
            />
          </Field>
          <Field label="Currency Symbol">
            <Input
              value={form.currency_symbol || "KES"}
              onChange={(e) => set("currency_symbol", e.target.value)}
            />
          </Field>
          <Field label="Tax Rate (%)">
            <Input
              type="number"
              value={form.tax_rate || "0"}
              onChange={(e) => set("tax_rate", e.target.value)}
            />
          </Field>
          <Field label="Receipt Footer">
            <Input
              value={form.receipt_footer || ""}
              onChange={(e) => set("receipt_footer", e.target.value)}
            />
          </Field>
        </Section>

        <Section
          icon={<MessageSquare className="h-5 w-5" />}
          title="Cloud Notifications"
          desc="Reports and alerts are delivered through Portal Notifications and email — Telegram has been permanently removed."
        >
          <p className="text-sm text-text2">
            Manage inbox preferences in the MugoByte Workspace under Notifications.
          </p>
        </Section>
      </div>
    </AppShell>
  );
}
