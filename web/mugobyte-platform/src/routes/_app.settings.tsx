import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, RefreshCw, Radio } from "lucide-react";
import { toast } from "sonner";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { GET, POST } from "@/lib/api";
import { useTheme } from "@/lib/theme";

const LIVE_URL_KEY = "mbt_live_dashboard_url";

export const Route = createFileRoute("/_app/settings")({
  component: SettingsPage,
  head: () => ({ meta: [{ title: "Settings | MugoByte" }] }),
});

function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const qc = useQueryClient();
  const [liveUrl, setLiveUrl] = useState("");

  useEffect(() => {
    try {
      setLiveUrl(localStorage.getItem(LIVE_URL_KEY) || "");
    } catch {
      /* ignore */
    }
  }, []);

  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });

  const settings = settingsQ.data || {};
  const [form, setForm] = useState<Record<string, string>>({});

  const saveMut = useMutation({
    mutationFn: () => POST("/settings", form),
    onSuccess: () => {
      toast.success("Settings saved");
      setForm({});
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: () => toast.error("Failed to save settings"),
  });

  function field(key: string) {
    return {
      value: form[key] !== undefined ? form[key] : (settings[key] || ""),
      onChange: (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [key]: e.target.value })),
    };
  }

  const FIELDS: { key: string; label: string; placeholder: string }[][] = [
    [
      { key: "shop_name", label: "Shop / Business name", placeholder: "ABC Supermarket" },
      { key: "shop_phone", label: "Phone", placeholder: "+254 7xx xxx xxx" },
    ],
    [
      { key: "shop_address", label: "Address", placeholder: "123 Main St, Nairobi" },
      { key: "currency", label: "Currency symbol", placeholder: "KES" },
    ],
    [
      { key: "vat_rate", label: "VAT rate (%)", placeholder: "16" },
      { key: "receipt_footer", label: "Receipt footer text", placeholder: "Thank you for shopping with us!" },
    ],
  ];

  return (
    <PageShell>
      <PageHeader
        eyebrow="Workspace"
        title="Settings"
        description="Profile preferences, appearance, and Live Shop deep-link for this portal session."
        actions={
          <Button variant="outline" onClick={() => settingsQ.refetch()}>
            <RefreshCw className="mr-1.5 h-4 w-4" />Reload
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 font-display">
              <Radio className="h-4 w-4 text-emerald-500" /> Live Shop URL
            </CardTitle>
            <CardDescription>
              Optional deep-link to your Cloudflare Live Dashboard (e.g. https://your-shop.mugobyte.com). Stored in this browser only — never mixed with cloud analytics.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="live-url">Live Dashboard URL</Label>
              <Input
                id="live-url"
                placeholder="https://your-shop.mugobyte.com"
                value={liveUrl}
                onChange={(e) => setLiveUrl(e.target.value)}
              />
            </div>
            <Button
              type="button"
              onClick={() => {
                const next = liveUrl.trim();
                try {
                  if (next) localStorage.setItem(LIVE_URL_KEY, next);
                  else localStorage.removeItem(LIVE_URL_KEY);
                  toast.success(next ? "Live Shop URL saved" : "Live Shop URL cleared");
                } catch {
                  toast.error("Could not save URL in this browser");
                }
              }}
            >
              <Save className="mr-1.5 h-4 w-4" />
              Save Live Shop link
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="font-display">Business settings</CardTitle>
            <CardDescription>Cloud / installation preferences when the settings API is available.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {settingsQ.isLoading ? (
              <p className="text-sm text-muted-foreground">Loading settings…</p>
            ) : (
              <>
                {FIELDS.map((row, i) => (
                  <div key={i} className="grid gap-4 sm:grid-cols-2">
                    {row.map(({ key, label, placeholder }) => (
                      <div key={key} className="space-y-1.5">
                        <Label>{label}</Label>
                        <Input placeholder={placeholder} {...field(key)} />
                      </div>
                    ))}
                  </div>
                ))}
                <div className="flex justify-end pt-2">
                  <Button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || Object.keys(form).length === 0}>
                    <Save className="mr-1.5 h-4 w-4" />
                    {saveMut.isPending ? "Saving…" : "Save settings"}
                  </Button>
                </div>
              </>
            )}
          </CardContent>
        </Card>
        </div>

        <div className="grid gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="font-display">Appearance</CardTitle>
              <CardDescription>Light, dark, or system — applied across the Portal.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {(["light", "dark", "system"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTheme(t)}
                  className={`flex w-full items-center gap-3 rounded-xl border p-3 text-sm transition ${
                    theme === t ? "border-primary bg-primary/5 font-semibold" : "border-border hover:bg-muted/40"
                  }`}
                >
                  <div className={`h-5 w-5 rounded-full border-2 ${theme === t ? "border-primary bg-primary" : "border-border"}`} />
                  <span className="capitalize">{t}</span>
                </button>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="font-display">Platform version</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-muted-foreground">Product</span><span className="font-mono">MugoByte Workspace</span></div>
              <Separator />
              <div className="flex justify-between"><span className="text-muted-foreground">Domain</span><span className="font-mono">portal.mugobyte.com</span></div>
              <Separator />
              <div className="flex justify-between"><span className="text-muted-foreground">Stack</span><span className="font-mono">React 19 · Flask</span></div>
            </CardContent>
          </Card>
        </div>
      </div>
    </PageShell>
  );
}
