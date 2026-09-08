import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, Table } from "@/components/ui-kit";
import { GET, POST, PUT, getUser } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/users")({
  component: Users,
});

const roleTone: Record<string, "gold" | "info" | "ok" | "muted" | "err"> = {
  superadmin: "gold",
  admin: "gold",
  manager: "info",
  cashier: "ok",
  viewer: "muted",
};

function Users() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const role = String(user?.role || getUser()?.role || "").toLowerCase();
  const canManage = role === "admin" || role === "superadmin";
  const isOwner = role === "superadmin";
  const [editor, setEditor] = useState<any | null>(null);

  const usersQ = useQuery({
    queryKey: ["users"],
    queryFn: () => GET<any[]>("/users"),
  });
  const users = Array.isArray(usersQ.data) ? usersQ.data : [];
  const err = usersQ.data && !Array.isArray(usersQ.data) ? (usersQ.data as any).error : null;

  return (
    <AppShell title="Users & Access">
      <PageHeader
        eyebrow="Admin"
        title="Users & Access"
        description="Staff accounts and roles. Super Admin can grant tabs and elevate staff from the web while the shop PC is online."
        actions={
          canManage ? (
            <Button
              onClick={() =>
                setEditor({
                  id: 0,
                  username: "",
                  full_name: "",
                  role: "cashier",
                  password: "",
                  is_active: 1,
                })
              }
            >
              Add user
            </Button>
          ) : null
        }
      />

      <Card>
        {usersQ.isLoading ? (
          <div className="py-12 text-center text-sm text-text2">Loading users…</div>
        ) : err ? (
          <div className="py-12 text-center text-sm text-err">{String(err)}</div>
        ) : (
          <Table head={["Name", "Username", "Role", "Status", "Last Login", ...(canManage ? ["Actions"] : [])]}>
            {users.map((u: any) => {
              let tabs = 0;
              try {
                const p = u.tab_permissions
                  ? typeof u.tab_permissions === "string"
                    ? JSON.parse(u.tab_permissions)
                    : u.tab_permissions
                  : [];
                tabs = Array.isArray(p) ? p.length : 0;
              } catch {
                tabs = 0;
              }
              return (
                <tr key={u.id}>
                  <td className="px-4 py-2.5 text-text font-medium">
                    {u.full_name || u.username}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-text2">{u.username}</td>
                  <td className="px-4 py-2.5">
                    <Badge tone={roleTone[u.role] || "muted"}>
                      {String(u.role || "").toUpperCase()}
                    </Badge>
                    {tabs > 0 ? (
                      <span className="ml-2 text-xs text-text2">{tabs} tabs</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge tone={u.is_active ? "ok" : "muted"}>
                      {u.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-text2">
                    {(u.last_login || "Never").toString().slice(0, 16)}
                  </td>
                  {canManage ? (
                    <td className="px-4 py-2.5">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          setEditor({
                            ...u,
                            password: "",
                            tab_permissions:
                              typeof u.tab_permissions === "string"
                                ? u.tab_permissions
                                : JSON.stringify(u.tab_permissions || []),
                          })
                        }
                      >
                        Edit
                      </Button>
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </Table>
        )}
      </Card>

      {editor ? (
        <UserEditor
          draft={editor}
          isOwner={isOwner}
          onClose={() => setEditor(null)}
          onDone={() => {
            setEditor(null);
            qc.invalidateQueries({ queryKey: ["users"] });
          }}
        />
      ) : null}
    </AppShell>
  );
}

function UserEditor({
  draft,
  isOwner,
  onClose,
  onDone,
}: {
  draft: any;
  isOwner: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState({ ...draft });
  const [busy, setBusy] = useState(false);
  const isNew = !form.id;

  const roleOptions = [
    ["cashier", "Cashier"],
    ["viewer", "Viewer"],
    ["manager", "Manager"],
    ["admin", "Admin"],
    ...(isOwner ? [["superadmin", "Super Admin"]] as const : []),
  ];

  async function submit() {
    if (!form.username?.trim()) {
      toast.error("Username required");
      return;
    }
    if (isNew && !form.password) {
      toast.error("Password required for new users");
      return;
    }
    setBusy(true);
    const payload: Record<string, unknown> = {
      username: form.username.trim(),
      full_name: form.full_name || form.username,
      role: form.role,
      is_active: form.is_active ? 1 : 0,
    };
    if (form.password) payload.password = form.password;
    if (form.tab_permissions != null && form.tab_permissions !== "") {
      try {
        payload.tab_permissions =
          typeof form.tab_permissions === "string"
            ? JSON.parse(form.tab_permissions)
            : form.tab_permissions;
      } catch {
        toast.error("tab_permissions must be valid JSON");
        setBusy(false);
        return;
      }
    }
    const res = isNew
      ? await POST<any>("/users", payload)
      : await PUT<any>(`/users/${form.id}`, payload);
    setBusy(false);
    if (res?.error) {
      toast.error(res.error);
      return;
    }
    if (res?.success || res?.id != null || (!isNew && res && !res.error)) {
      toast.success(isNew ? "User created" : "User updated");
      onDone();
      return;
    }
    toast.error("Save failed");
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg rounded-xl border border-border bg-card p-5 shadow-xl">
        <h3 className="text-lg font-semibold text-text mb-4">
          {isNew ? "Add user" : "Edit user"}
        </h3>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-xs font-medium text-text2">
            Username
            <Input
              value={form.username || ""}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              disabled={!isNew}
            />
          </label>
          <label className="block text-xs font-medium text-text2">
            Full name
            <Input
              value={form.full_name || ""}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            />
          </label>
          <label className="block text-xs font-medium text-text2">
            Role
            <select
              className="mt-1 w-full rounded-md border border-border bg-panel px-3 py-2 text-sm text-text"
              value={form.role || "cashier"}
              onChange={(e) => setForm({ ...form, role: e.target.value })}
            >
              {roleOptions.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs font-medium text-text2">
            Password {isNew ? "" : "(leave blank to keep)"}
            <Input
              type="password"
              value={form.password || ""}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              autoComplete="new-password"
            />
          </label>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm text-text2">
          <input
            type="checkbox"
            checked={!!form.is_active}
            onChange={(e) => setForm({ ...form, is_active: e.target.checked ? 1 : 0 })}
          />
          Active
        </label>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={busy}>
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}
