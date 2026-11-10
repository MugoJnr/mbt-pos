import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Smartphone } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Button, Card, Input, PageHeader } from "@/components/ui-kit";
import { GET, POST, PUT } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/mpesa")({
  component: MpesaCentre,
});

type Profile = {
  id: string;
  name: string;
  merchant_type: string;
  till_number?: string;
  paybill_number?: string;
  shortcode?: string;
  business_name?: string;
  status?: string;
  is_default?: boolean;
  credentials_stored?: boolean;
  environment?: string;
};

type Payment = {
  id: string;
  state?: string;
  verification?: string;
  amount_shillings?: number;
  phone_masked?: string;
  receipt_code?: string;
  sale_reference?: string;
  customer_message?: string;
  simulated?: boolean;
  created_at?: string;
  profile_id?: string;
};

function MpesaCentre() {
  const { user } = useAuth();
  const role = String(user?.role || "");
  const canConfigure = role === "admin" || role === "superadmin";
  const canReview = canConfigure || role === "manager";
  const qc = useQueryClient();
  const [form, setForm] = useState({
    name: "",
    merchant_type: "till",
    till_number: "",
    paybill_number: "",
    shortcode: "",
    business_name: "",
    consumer_key: "",
    consumer_secret: "",
    passkey: "",
    callback_url: "",
  });
  const [token, setToken] = useState("");
  const [matchSale, setMatchSale] = useState<Record<string, string>>({});
  const [matchReason, setMatchReason] = useState<Record<string, string>>({});

  const diagnostics = useQuery({
    queryKey: ["mpesa-diagnostics"],
    queryFn: () => GET<Record<string, any>>("/mpesa/diagnostics"),
  });
  const profiles = useQuery({
    queryKey: ["mpesa-profiles"],
    queryFn: () => GET<{ profiles?: Profile[] }>("/mpesa/profiles"),
  });
  const payments = useQuery({
    queryKey: ["mpesa-payments"],
    queryFn: () => GET<{ payments?: Payment[] }>("/mpesa/payments"),
  });
  const summary = useQuery({
    queryKey: ["mpesa-summary"],
    queryFn: () => GET<Record<string, any>>("/mpesa/summary"),
    enabled: canReview,
  });
  const incoming = useQuery({
    queryKey: ["mpesa-incoming"],
    queryFn: () => GET<{ incoming?: Array<Record<string, any>> }>("/mpesa/incoming"),
    enabled: canReview,
  });

  const saveProfile = useMutation({
    mutationFn: () => POST<Record<string, any>>("/mpesa/profiles", form),
    onSuccess: (result) => {
      if (!result || result.error) {
        toast.error(result?.error || "The profile was not saved");
        return;
      }
      setForm({
        name: "",
        merchant_type: "till",
        till_number: "",
        paybill_number: "",
        shortcode: "",
        business_name: "",
        consumer_key: "",
        consumer_secret: "",
        passkey: "",
        callback_url: "",
      });
      toast.success("Profile saved. The secrets are not shown again.");
      qc.invalidateQueries({ queryKey: ["mpesa-profiles"] });
    },
  });

  const rows = profiles.data?.profiles || [];
  const paymentRows = payments.data?.payments || [];
  const incomingRows = incoming.data?.incoming || [];
  const totals = summary.data || {};

  return (
    <AppShell title="M-Pesa">
      <PageHeader
        eyebrow="Payments"
        title="M-Pesa"
        icon={<Smartphone className="h-4 w-4" />}
        description="Each shop keeps its own till or paybill. A phone prompt is not payment until a status query matches the amount."
      />

      <div className="grid gap-3 md:grid-cols-4 mb-4">
        <Card><div className="p-3"><div className="text-xs text-text2">Verified with Safaricom</div><div className="text-xl font-bold">{totals.verified_daraja?.count ?? 0}</div></div></Card>
        <Card><div className="p-3"><div className="text-xs text-text2">Simulated</div><div className="text-xl font-bold">{totals.simulated?.count ?? 0}</div></div></Card>
        <Card><div className="p-3"><div className="text-xs text-text2">Manual, not verified</div><div className="text-xl font-bold">{totals.manual?.count ?? 0}</div></div></Card>
        <Card><div className="p-3"><div className="text-xs text-text2">Unknown</div><div className="text-xl font-bold">{totals.unknown?.count ?? 0}</div></div></Card>
      </div>

      <Card className="mb-4">
        <div className="p-4 space-y-2 text-sm">
          <div className="font-semibold">Service</div>
          <p className="text-text2">{diagnostics.data?.message || "Checking the payment service."}</p>
          <p>Address saved: {diagnostics.data?.service_address_set ? "yes" : "no"}</p>
          <p>Service answered: {diagnostics.data?.service_reachable ? "yes" : "no"}</p>
          <p>Service token: {diagnostics.data?.service_authentication || "not configured"}</p>
          <p>Callback verified: no. Production: off.</p>
          {canConfigure ? (
            <div className="flex flex-wrap gap-2">
              <Input
                type="password"
                value={token}
                placeholder="Payment service token"
                onChange={(e) => setToken(e.target.value)}
                className="max-w-sm"
              />
              <Button type="button" variant="secondary" onClick={() => {
                void PUT("/mpesa/service-token", { service_token: token }).then((result) => {
                  if (!result || result.error) toast.error(result?.error || "Token was not saved");
                  else {
                    setToken("");
                    toast.success("Token saved on this shop computer. It is not shown again.");
                    qc.invalidateQueries({ queryKey: ["mpesa-diagnostics"] });
                  }
                });
              }}>Save token</Button>
            </div>
          ) : null}
        </div>
      </Card>

      {canConfigure ? (
        <Card className="mb-4">
          <div className="p-4 grid gap-2 md:grid-cols-2">
            <div className="md:col-span-2 font-semibold">New merchant profile</div>
            <Input placeholder="Profile name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <select className="h-10 rounded-md border border-border bg-input px-2" value={form.merchant_type} onChange={(e) => setForm({ ...form, merchant_type: e.target.value })}>
              <option value="till">Buy Goods Till</option>
              <option value="paybill">Paybill</option>
            </select>
            <Input placeholder="Till number" value={form.till_number} onChange={(e) => setForm({ ...form, till_number: e.target.value })} />
            <Input placeholder="Paybill number" value={form.paybill_number} onChange={(e) => setForm({ ...form, paybill_number: e.target.value })} />
            <Input placeholder="Business shortcode" value={form.shortcode} onChange={(e) => setForm({ ...form, shortcode: e.target.value })} />
            <Input placeholder="Name on the receipt" value={form.business_name} onChange={(e) => setForm({ ...form, business_name: e.target.value })} />
            <Input placeholder="Callback URL, optional" value={form.callback_url} onChange={(e) => setForm({ ...form, callback_url: e.target.value })} />
            <Input type="password" placeholder="Consumer key" value={form.consumer_key} onChange={(e) => setForm({ ...form, consumer_key: e.target.value })} />
            <Input type="password" placeholder="Consumer secret" value={form.consumer_secret} onChange={(e) => setForm({ ...form, consumer_secret: e.target.value })} />
            <Input type="password" placeholder="Passkey" value={form.passkey} onChange={(e) => setForm({ ...form, passkey: e.target.value })} />
            <Button type="button" disabled={saveProfile.isPending} onClick={() => saveProfile.mutate()}>Save profile</Button>
            <p className="md:col-span-2 text-sm text-text2">Sandbox only. Secrets are sent once to the payment service and are not stored in shop settings.</p>
          </div>
        </Card>
      ) : null}

      <Card className="mb-4">
        <div className="p-4 space-y-2">
          <div className="font-semibold">Profiles</div>
          {rows.length === 0 ? <p className="text-sm text-text2">No merchant profile yet. Manual till and paybill numbers in Settings still print on receipts.</p> : null}
          {rows.map((row) => (
            <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 border-t border-border py-2 text-sm">
              <div>
                <div className="font-semibold">{row.name}</div>
                <div className="text-text2">
                  {row.merchant_type} · {row.till_number || row.paybill_number || row.shortcode} · {row.status} · {row.environment}
                  {row.credentials_stored ? " · secrets stored" : ""}
                </div>
              </div>
              {canConfigure ? (
                <div className="flex gap-2">
                  <Button type="button" variant="secondary" onClick={() => {
                    void POST(`/mpesa/profiles/${row.id}/authenticate`, {}).then((result) => {
                      toast.message(result?.message || result?.error || "Done");
                    });
                  }}>Test sign-in</Button>
                  <Button type="button" variant="secondary" onClick={() => {
                    void POST(`/mpesa/profiles/${row.id}/activate`, { make_default: true }).then((result) => {
                      if (result?.error) toast.error(result.error);
                      else {
                        toast.success("Profile is active for this shop.");
                        qc.invalidateQueries({ queryKey: ["mpesa-profiles"] });
                      }
                    });
                  }}>Use for this shop</Button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </Card>

      <Card className="mb-4">
        <div className="p-4 space-y-2">
          <div className="font-semibold">Payments</div>
          {paymentRows.map((row) => (
            <div key={row.id} className="border-t border-border py-2 text-sm">
              <div className="font-semibold">{row.receipt_code || "No code yet"} · {row.amount_shillings ?? ""} KSh · {row.state}</div>
              <div className="text-text2">{row.customer_message} {row.phone_masked ? `· ${row.phone_masked}` : ""} {row.simulated ? "· simulated" : ""}</div>
            </div>
          ))}
          {paymentRows.length === 0 ? <p className="text-sm text-text2">No phone prompts yet.</p> : null}
        </div>
      </Card>

      {canReview ? (
        <Card>
          <div className="p-4 space-y-2">
            <div className="font-semibold">Incoming payments</div>
            {incomingRows.map((row) => (
              <div key={row.id} className="border-t border-border py-2 text-sm space-y-1">
                <div>{row.provider_ref} · {row.amount_shillings} KSh · {row.state}</div>
                {row.state === "unmatched" || row.state === "mismatch" ? (
                  <div className="flex flex-wrap gap-2">
                    <Input placeholder="Sale id" value={matchSale[row.id] || ""} onChange={(e) => setMatchSale({ ...matchSale, [row.id]: e.target.value })} className="max-w-[140px]" />
                    <Input placeholder="Reason" value={matchReason[row.id] || ""} onChange={(e) => setMatchReason({ ...matchReason, [row.id]: e.target.value })} className="max-w-xs" />
                    <Button type="button" variant="secondary" onClick={() => {
                      void POST(`/mpesa/incoming/${row.id}/match`, {
                        sale_id: Number(matchSale[row.id]),
                        reason: matchReason[row.id] || "",
                      }).then((result) => {
                        if (result?.error) toast.error(result.error);
                        else toast.success("Matched. The original incoming record is kept.");
                        qc.invalidateQueries({ queryKey: ["mpesa-incoming"] });
                      });
                    }}>Match</Button>
                  </div>
                ) : null}
              </div>
            ))}
            {incomingRows.length === 0 ? <p className="text-sm text-text2">No incoming paybill or till notifications yet.</p> : null}
          </div>
        </Card>
      ) : null}
    </AppShell>
  );
}
