import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@/components/ui-kit";
import { GET, PUT, getUser } from "@/lib/api";

type Activity = { key: string; label: string; mode: "direct" | "admin_pin" | "request"; locked_direct?: boolean; lock_reason?: string; override?: boolean };
type Section = { tab: string; enabled: boolean; activities: Activity[] };
type Screen = { tabs?: Section[]; accessible_tabs?: string[]; error?: string };

const MODES: { id: Activity["mode"]; label: string }[] = [
  { id: "direct", label: "Direct" },
  { id: "admin_pin", label: "Admin PIN" },
  { id: "request", label: "Request approval" },
];

export function UserCapabilities({ account, onClose }: { account: any; onClose: () => void }) {
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string>("");
  const [msg, setMsg] = useState("");
  const [saving, setSaving] = useState("");
  const mine = Number(getUser()?.id || 0) === Number(account?.id || 0);
  const role = String(account?.role || "").toLowerCase();
  const screenQ = useQuery({
    queryKey: ["user-capabilities", account?.id],
    queryFn: () => GET<Screen>(`/users/${account.id}/capabilities`),
    enabled: !mine && role !== "superadmin",
  });

  useEffect(() => { setMsg(""); }, [account?.id]);

  if (mine) return <p className="text-sm text-text2">You cannot change your own permissions.</p>;
  if (role === "superadmin") {
    return <p className="text-sm text-text2">Super Admin access follows that role. Change the role to reduce it.</p>;
  }

  const sections = screenQ.data?.tabs || [];
  const needle = query.trim().toLowerCase();

  async function save(body: Record<string, unknown>, label: string) {
    setSaving(label);
    setMsg("");
    const saved = await PUT<any>(`/users/${account.id}`, body);
    setSaving("");
    if (!saved?.success) {
      setMsg(saved?.error || "That change was not saved.");
      return;
    }
    setMsg("Saved.");
    await qc.invalidateQueries({ queryKey: ["user-capabilities", account.id] });
    await qc.invalidateQueries({ queryKey: ["users"] });
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-text2">
        A ticked tab is on this person's menu. Inside it, each activity is Direct, Admin PIN, or Request approval. One choice is used. The same settings apply on the till and on this dashboard.
      </p>
      <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search activities" aria-label="Search activities" />
      {screenQ.isLoading ? <p className="text-sm text-text2">Loading capabilities…</p> : null}
      <div className="max-h-[28rem] space-y-2 overflow-auto pr-1">
        {sections.map((section) => {
          const activities = section.activities.filter((item) => !needle || `${item.label} ${section.tab}`.toLowerCase().includes(needle));
          if (needle && !activities.length && !section.tab.includes(needle)) return null;
          const shown = open === section.tab;
          return (
            <div key={section.tab} className="rounded-xl border border-border">
              <div className="flex items-center gap-3 px-3 py-2">
                <input
                  type="checkbox"
                  aria-label={`${section.tab} access`}
                  checked={section.enabled}
                  onChange={(e) => {
                    const tabs = sections.filter((item) => item.tab === section.tab ? e.target.checked : item.enabled).map((item) => item.tab);
                    void save({ tab_permissions: tabs }, section.tab);
                  }}
                />
                <button type="button" className="flex-1 text-left text-sm font-semibold capitalize text-text" onClick={() => setOpen(shown ? "" : section.tab)}>
                  {section.tab.replaceAll("_", " ")}
                </button>
                <span className="text-xs text-text2">{section.enabled ? "On" : "Hidden"}</span>
              </div>
              {shown && section.enabled ? (
                <div className="space-y-2 border-t border-border px-3 py-2">
                  {activities.map((item) => (
                    <div key={item.key} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                      <div className="text-sm text-text">{item.label}</div>
                      <div className="flex flex-wrap gap-1" role="radiogroup" aria-label={item.label}>
                        {MODES.map((mode) => (
                          <button
                            key={mode.id}
                            type="button"
                            aria-pressed={item.mode === mode.id}
                            title={mode.id === "direct" && item.lock_reason ? item.lock_reason : mode.label}
                            disabled={saving === item.key || (mode.id === "direct" && item.locked_direct)}
                            className={`rounded-lg border px-2 py-1 text-xs ${item.mode === mode.id ? "border-gold bg-gold/15 font-semibold text-text" : "border-border text-text2"}`}
                            onClick={() => void save({ permission_modes: { [item.key]: mode.id } }, item.key)}
                          >
                            {mode.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                  {!activities.length ? <p className="text-xs text-text2">This tab has no separate activities.</p> : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      <p className="text-sm text-text2">{saving ? "Saving…" : msg}</p>
      <div className="flex justify-end">
        <Button variant="ghost" onClick={onClose}>Close</Button>
      </div>
    </div>
  );
}

const ROLE_NAMES = ["cashier", "viewer", "manager", "admin"] as const;

export function RoleDefaults() {
  const [role, setRole] = useState<(typeof ROLE_NAMES)[number]>("cashier");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const defaultsQ = useQuery({
    queryKey: ["capability-defaults"],
    queryFn: () => GET<{ profiles?: Record<string, { tabs?: string[]; modes?: Record<string, string> }>; error?: string }>("/capability-defaults"),
  });
  const policyQ = useQuery({
    queryKey: ["capability-policy"],
    queryFn: () => GET<{ locks?: Record<string, string> }>("/capability-policy"),
  });
  const profile = defaultsQ.data?.profiles?.[role];
  const tabs = profile?.tabs || [];
  const stock = profile?.modes?.["inventory.adjust_stock"] || "request";

  async function saveProfile() {
    setBusy(true);
    setMsg("");
    const saved = await PUT<any>("/capability-defaults", {
      role,
      tabs,
      modes: { ...(profile?.modes || {}), "inventory.adjust_stock": stock },
    });
    setBusy(false);
    setMsg(saved?.success ? "Role default saved. New people in this role receive it." : (saved?.error || "The default was not saved."));
  }

  return (
    <div className="mb-4 rounded-xl border border-border bg-card p-4">
      <div className="text-sm font-semibold text-text">Default capabilities</div>
      <p className="mt-1 text-sm text-text2">
        New accounts start from the role default. A person who was customized keeps that setup until you choose to replace it.
        Stock reduction starts as Request approval. Direct stays visible. A locked Direct choice shows the reason, and only a Super Admin can change that policy.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <select aria-label="Role default" value={role} onChange={(e) => setRole(e.target.value as typeof role)} className="h-10 rounded-lg border border-border bg-input px-2 text-sm">
          {ROLE_NAMES.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
        <span className="text-sm text-text2">{tabs.length} tabs · stock reduction {stock.replace("_", " ")}</span>
        <Button disabled={busy || !profile} onClick={() => void saveProfile()}>{busy ? "Saving…" : "Save role default"}</Button>
      </div>
      {policyQ.data?.locks ? (
        <p className="mt-2 text-xs text-text2">{Object.keys(policyQ.data.locks).length} activities keep Direct locked until you change the security policy.</p>
      ) : null}
      {msg ? <p className="mt-2 text-sm text-text2">{msg}</p> : null}
    </div>
  );
}
