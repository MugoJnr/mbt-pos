import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@/components/ui-kit";
import { GET, PUT, getUser } from "@/lib/api";

type Item = { key: string; label: string; grantable: boolean; inherited: boolean };
type Group = { group: string; items: Item[] };

function asList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String);
  try {
    const parsed = JSON.parse(String(value || "[]"));
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

export function UserCapabilities({
  account,
  onClose,
}: {
  account: any;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [catalogue, setCatalogue] = useState<Group[]>([]);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const role = String(account?.role || "").toLowerCase();
  const mine = Number(getUser()?.id || 0) === Number(account?.id || 0);
  const grants = asList(account?.permission_grants);
  const denials = asList(account?.permission_denials);

  useEffect(() => {
    let live = true;
    void GET<Group[]>(`/permission-catalogue?role=${encodeURIComponent(role)}`).then((rows) => {
      if (!live) return;
      const groups = Array.isArray(rows) ? rows : [];
      setCatalogue(groups);
      const next: Record<string, boolean> = {};
      groups.forEach((group) => group.items.forEach((item) => {
        next[item.key] = (item.inherited && !denials.includes(item.key)) || grants.includes(item.key);
      }));
      setChecked(next);
    });
    return () => { live = false; };
  }, [account?.id, role]);

  if (mine) return <p className="text-sm text-text2">You cannot change your own permissions.</p>;
  if (role === "superadmin") {
    return <p className="text-sm text-text2">Super Admin access follows that role. Change the role to reduce it.</p>;
  }

  const needle = query.trim().toLowerCase();
  return (
    <div className="space-y-3">
      <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search capabilities" aria-label="Search capabilities" />
      <div className="max-h-80 space-y-3 overflow-auto pr-1">
        {catalogue.map((group) => {
          const items = group.items.filter((item) => !needle || `${item.label} ${item.key}`.toLowerCase().includes(needle));
          if (!items.length) return null;
          return (
            <div key={group.group}>
              <div className="text-[11px] font-bold uppercase tracking-wide text-text2">{group.group}</div>
              {items.map((item) => (
                <label key={item.key} className="mt-1 flex items-center gap-2 text-sm text-text">
                  <input
                    type="checkbox"
                    checked={Boolean(checked[item.key])}
                    disabled={!item.grantable && !item.inherited}
                    title={!item.grantable && !item.inherited ? "This stays with the role and cannot be delegated." : item.inherited ? "Included with the role. Untick to remove it." : "Extra capability, outside the role."}
                    onChange={(e) => setChecked((prev) => ({ ...prev, [item.key]: e.target.checked }))}
                  />
                  <span>{item.label}{item.inherited ? "" : " · extra"}</span>
                </label>
              ))}
            </div>
          );
        })}
      </div>
      {msg ? <p className="text-sm text-text2">{msg}</p> : null}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Close</Button>
        <Button
          disabled={busy || !catalogue.length}
          onClick={async () => {
            const items = catalogue.flatMap((group) => group.items);
            const removing = items.filter((item) => item.inherited && !checked[item.key]).map((item) => item.key);
            const adding = items.filter((item) => !item.inherited && item.grantable && checked[item.key]).map((item) => item.key);
            if (removing.length && !window.confirm("This removes access the role normally has. Save anyway?")) return;
            setBusy(true);
            setMsg("");
            const saved = await PUT<any>(`/users/${account.id}`, {
              permission_grants: adding,
              permission_denials: removing,
            });
            setBusy(false);
            if (!saved?.success) {
              setMsg(saved?.error || "The permissions were not saved.");
              return;
            }
            setMsg("Saved. The change applies on the next action.");
            await qc.invalidateQueries({ queryKey: ["users"] });
          }}
        >
          Save capabilities
        </Button>
      </div>
    </div>
  );
}
