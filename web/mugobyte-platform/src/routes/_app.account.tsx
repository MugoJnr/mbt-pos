import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  UserCircle2, Shield, Key, Bell, Smartphone, Globe, Palette,
  Save, AlertCircle,
} from "lucide-react";
import { toast } from "sonner";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { GET, POST } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/_app/account")({
  component: AccountPage,
  head: () => ({ meta: [{ title: "Profile | MugoByte" }] }),
});

function AccountPage() {
  const { user } = useAuth();
  const qc = useQueryClient();

  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => GET<Record<string, string>>("/settings"),
  });

  const settings = settingsQ.data || {};
  const [shopName, setShopName] = useState(() => settings.shop_name || "");
  const [currency, setCurrency] = useState(() => settings.currency || "KES");

  const saveMut = useMutation({
    mutationFn: () =>
      POST("/settings", { shop_name: shopName, currency }),
    onSuccess: () => {
      toast.success("Settings saved");
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: () => toast.error("Save failed"),
  });

  const initials = String(user?.full_name || user?.username || "MB")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <PageShell>
      <PageHeader
        eyebrow="Platform"
        title="Profile & Account"
        description="Shared identity, preferences and security settings across MugoByte Platform."
      />

      <Tabs defaultValue="profile">
        <TabsList className="mb-4">
          <TabsTrigger value="profile"><UserCircle2 className="mr-1.5 h-3.5 w-3.5" />Profile</TabsTrigger>
          <TabsTrigger value="business"><Globe className="mr-1.5 h-3.5 w-3.5" />Business</TabsTrigger>
          <TabsTrigger value="security"><Shield className="mr-1.5 h-3.5 w-3.5" />Security</TabsTrigger>
          <TabsTrigger value="sessions"><Smartphone className="mr-1.5 h-3.5 w-3.5" />Sessions</TabsTrigger>
          <TabsTrigger value="notifications"><Bell className="mr-1.5 h-3.5 w-3.5" />Notifications</TabsTrigger>
        </TabsList>

        <TabsContent value="profile">
          <div className="grid gap-4 lg:grid-cols-[1fr_2fr]">
            <Card>
              <CardContent className="flex flex-col items-center gap-4 p-8">
                <Avatar className="h-24 w-24">
                  <AvatarFallback className="bg-primary/15 text-3xl font-bold text-primary">{initials}</AvatarFallback>
                </Avatar>
                <div className="text-center">
                  <div className="font-display text-lg font-semibold">{user?.full_name || user?.username}</div>
                  <div className="text-sm text-muted-foreground">{user?.email || "—"}</div>
                  <Badge variant="secondary" className="mt-2">{user?.role || "member"}</Badge>
                </div>
                <Button variant="outline" size="sm" className="w-full">Change photo</Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="font-display">Personal information</CardTitle>
                <CardDescription>Shared across all MugoByte Platform applications.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Full name" value={user?.full_name as string} placeholder="Your name" />
                  <Field label="Username" value={user?.username as string} placeholder="@username" />
                  <Field label="Email" value={user?.email as string} placeholder="you@email.com" type="email" />
                  <Field label="Phone" value="" placeholder="+254 7xx xxx xxx" />
                </div>
                <Separator />
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Language" value="English" placeholder="" />
                  <Field label="Timezone" value="Africa/Nairobi" placeholder="" />
                </div>
                <div className="flex justify-end">
                  <Button onClick={() => toast.info("Profile update requires backend user management API")}>
                    <Save className="mr-1.5 h-4 w-4" />Save changes
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="business">
          <Card>
            <CardHeader>
              <CardTitle className="font-display">Business settings</CardTitle>
              <CardDescription>Shop name, currency and other POS-wide configuration.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {settingsQ.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading settings…</p>
              ) : (
                <>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label>Shop name</Label>
                      <Input
                        value={shopName || settings.shop_name || ""}
                        onChange={(e) => setShopName(e.target.value)}
                        placeholder="ABC Supermarket"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label>Currency symbol</Label>
                      <Input
                        value={currency || settings.currency || "KES"}
                        onChange={(e) => setCurrency(e.target.value)}
                        placeholder="KES"
                      />
                    </div>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {["vat_rate", "receipt_footer", "shop_phone", "shop_address"].map((k) => (
                      <div key={k} className="space-y-1.5">
                        <Label>{k.replace(/_/g, " ")}</Label>
                        <Input defaultValue={settings[k] || ""} placeholder="—" />
                      </div>
                    ))}
                  </div>
                  <div className="flex justify-end">
                    <Button onClick={() => saveMut.mutate()} disabled={saveMut.isPending}>
                      <Save className="mr-1.5 h-4 w-4" />
                      {saveMut.isPending ? "Saving…" : "Save settings"}
                    </Button>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="security">
          <Card>
            <CardHeader>
              <CardTitle className="font-display">Security</CardTitle>
              <CardDescription>Password, sessions and two-factor authentication.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div>
                <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold"><Key className="h-4 w-4" />Change password</h3>
                <div className="grid max-w-md gap-3">
                  <div className="space-y-1.5"><Label>Current password</Label><Input type="password" /></div>
                  <div className="space-y-1.5"><Label>New password</Label><Input type="password" /></div>
                  <div className="space-y-1.5"><Label>Confirm password</Label><Input type="password" /></div>
                  <Button className="w-fit" onClick={() => toast.info("Password change wired to /api/users/{id} PUT endpoint")}>Update password</Button>
                </div>
              </div>
              <Separator />
              <div className="rounded-xl border border-warning/30 bg-warning/5 p-4 text-sm text-warning">
                <AlertCircle className="mb-2 h-4 w-4" />
                Two-factor authentication (TOTP) is planned in a future platform update.
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="sessions">
          <Card>
            <CardHeader>
              <CardTitle className="font-display">Active sessions</CardTitle>
              <CardDescription>Devices and browsers currently authenticated to your account.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="rounded-xl border border-dashed border-border/70 p-6 text-center text-sm text-muted-foreground">
                Session devices will appear here when platform session management is connected.
                This browser session is active now.
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="notifications">
          <Card>
            <CardHeader>
              <CardTitle className="font-display">Notification preferences</CardTitle>
              <CardDescription>Choose how MugoByte Platform and MBT POS notify you.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {[
                { label: "Daily sales summary", desc: "End-of-day report delivered to the notification center and email." },
                { label: "Low stock alerts", desc: "When any product falls below minimum stock level." },
                { label: "License expiry warnings", desc: "30, 14, 7 and 1 day warnings before license expires." },
                { label: "Backup status", desc: "Notify when cloud backup succeeds or fails." },
                { label: "Device offline", desc: "Notify when a registered POS device goes offline." },
                { label: "Platform announcements", desc: "Updates, new features and security notices." },
              ].map((item) => (
                <div key={item.label} className="flex items-center justify-between rounded-xl border border-border/70 p-4">
                  <div>
                    <div className="font-medium">{item.label}</div>
                    <div className="text-sm text-muted-foreground">{item.desc}</div>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => toast.info("Notification preferences wired in future platform update")}>
                    Configure
                  </Button>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}

function Field({ label, value, placeholder, type = "text" }: { label: string; value: string; placeholder: string; type?: string }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <Input type={type} defaultValue={value || ""} placeholder={placeholder} />
    </div>
  );
}
