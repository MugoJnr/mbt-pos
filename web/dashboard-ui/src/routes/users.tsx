import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, PageHeader, Table } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";

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
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [pwMsg, setPwMsg] = useState("");
  const [newName, setNewName] = useState("");
  const [newUsername, setNewUsername] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newRole, setNewRole] = useState("cashier");
  const [userMsg, setUserMsg] = useState("");
  const usersQ = useQuery({
    queryKey: ["users"],
    queryFn: () => GET<any[]>("/users"),
  });
  const sessionsQ = useQuery({
    queryKey: ["sessions"],
    queryFn: () => GET<any>("/sessions"),
    refetchInterval: 15000,
  });
  const tillQ = useQuery({
    queryKey: ["till-signins"],
    queryFn: () => GET<any>("/till/signins"),
    refetchInterval: 3000,
  });
  const users = Array.isArray(usersQ.data) ? usersQ.data : [];
  const err = usersQ.data && !Array.isArray(usersQ.data) ? (usersQ.data as any).error : null;

  return (
    <AppShell title="Users & Access">
      <PageHeader
        eyebrow="Admin"
        title="Users & Access"
        description="Change your own password here. An admin can add a staff account. Ending a till sign-in asks that till to return to the login screen."
      />

      <Card className="mb-4">
        <div className="p-4 space-y-3">
          <div className="text-sm font-semibold text-text">Change password</div>
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              placeholder="Current password"
              className="h-11 rounded-lg border border-border bg-input px-3 text-sm text-text"
            />
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="New password"
              className="h-11 rounded-lg border border-border bg-input px-3 text-sm text-text"
            />
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Confirm new password"
              className="h-11 rounded-lg border border-border bg-input px-3 text-sm text-text"
            />
          </div>
          <Button
            onClick={async () => {
              setPwMsg("");
              const res = await POST<any>("/account/password", {
                current_password: currentPassword,
                new_password: newPassword,
                confirm_password: confirmPassword,
              });
              if (res?.success) {
                setPwMsg("Password changed.");
                setCurrentPassword("");
                setNewPassword("");
                setConfirmPassword("");
              } else {
                setPwMsg(res?.error || "Could not change password");
              }
            }}
          >
            Save password
          </Button>
          {pwMsg ? <div className="text-sm text-text2">{pwMsg}</div> : null}
        </div>
      </Card>

      <Card className="mb-4">
        <div className="p-4 space-y-3">
          <div className="text-sm font-semibold text-text">Add a staff account</div>
          <div className="grid gap-2 sm:grid-cols-2">
            <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Full name" className="h-11 rounded-lg border border-border bg-input px-3 text-sm text-text" />
            <input value={newUsername} onChange={(e) => setNewUsername(e.target.value)} placeholder="Username" className="h-11 rounded-lg border border-border bg-input px-3 text-sm text-text" />
            <input type="password" value={newUserPassword} onChange={(e) => setNewUserPassword(e.target.value)} placeholder="Password" className="h-11 rounded-lg border border-border bg-input px-3 text-sm text-text" />
            <select value={newRole} onChange={(e) => setNewRole(e.target.value)} className="h-11 rounded-lg border border-border bg-input px-3 text-sm text-text">
              <option value="cashier">Cashier</option>
              <option value="manager">Manager</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <Button
            onClick={async () => {
              setUserMsg("");
              const res = await POST<any>("/users", {
                full_name: newName,
                username: newUsername,
                password: newUserPassword,
                role: newRole,
              });
              if (res?.success) {
                setUserMsg("Account created.");
                setNewName("");
                setNewUsername("");
                setNewUserPassword("");
                qc.invalidateQueries({ queryKey: ["users"] });
              } else {
                setUserMsg(res?.error || "Could not create that account.");
              }
            }}
          >
            Create account
          </Button>
          {userMsg ? <div className="text-sm text-text2">{userMsg}</div> : null}
        </div>
      </Card>

      <Card className="mb-4">
        <div className="p-4">
          <div className="mb-1 text-sm font-semibold text-text">Till sign-ins</div>
          <div className="mb-3 text-xs text-text2">
            End sign-in returns that person to the MBT POS login screen. It does not revoke the license.
          </div>
          {tillQ.isLoading ? (
            <div className="text-sm text-text2">Loading till sign-ins…</div>
          ) : (
            <Table head={["Person", "Role", "State", "Since", ""]}>
              {(Array.isArray(tillQ.data?.signins) ? tillQ.data.signins : [])
                .filter((s: any) => s.state !== "signed_out")
                .map((s: any) => (
                  <tr key={s.id}>
                    <td className="px-4 py-2.5 text-text">{s.full_name || s.username}</td>
                    <td className="px-4 py-2.5 text-text2">{s.role}</td>
                    <td className="px-4 py-2.5 text-xs text-text2">
                      {s.state === "pending"
                        ? "Pending — till has not signed out yet"
                        : s.state === "offline"
                          ? "Till offline"
                          : "Signed in on the till"}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-text2">{String(s.started_at || "").slice(0, 16)}</td>
                    <td className="px-4 py-2.5">
                      <Button
                        variant="ghost"
                        disabled={s.state === "pending"}
                        onClick={async () => {
                          const res = await POST<any>(`/till/signins/${s.id}/end`);
                          if (res?.error) setUserMsg(res.error);
                          qc.invalidateQueries({ queryKey: ["till-signins"] });
                        }}
                      >
                        {s.state === "pending" ? "Pending" : "End till sign-in"}
                      </Button>
                    </td>
                  </tr>
                ))}
            </Table>
          )}
        </div>
      </Card>

      <Card className="mb-4">
        <div className="p-4">
          <div className="mb-3 text-sm font-semibold text-text">Web dashboard sign-ins</div>
          {sessionsQ.isLoading ? (
            <div className="text-sm text-text2">Loading sessions…</div>
          ) : (
            <Table head={["Account", "Role", "Where", "Since", ""]}>
              {(Array.isArray(sessionsQ.data?.sessions) ? sessionsQ.data.sessions : []).map((s: any) => (
                <tr key={s.id}>
                  <td className="px-4 py-2.5 text-text">{s.full_name || s.username}</td>
                  <td className="px-4 py-2.5 text-text2">{s.role}</td>
                  <td className="px-4 py-2.5 text-xs text-text2">{s.ip || "this till"}</td>
                  <td className="px-4 py-2.5 text-xs text-text2">{String(s.created_at || "").slice(0, 16)}</td>
                  <td className="px-4 py-2.5">
                    <Button
                      variant="ghost"
                      onClick={async () => {
                        const res = await POST<any>(`/sessions/${s.id}/revoke`);
                        if (res?.error) setUserMsg(res.error);
                        qc.invalidateQueries({ queryKey: ["sessions"] });
                      }}
                    >
                      Log out
                    </Button>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </div>
      </Card>

      <Card>
        {usersQ.isLoading ? (
          <div className="py-12 text-center text-sm text-text2">Loading users…</div>
        ) : err ? (
          <div className="py-12 text-center text-sm text-err">{String(err)}</div>
        ) : (
          <Table head={["Name", "Username", "Role", "Status", "Last Login"]}>
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
                </tr>
              );
            })}
          </Table>
        )}
      </Card>
    </AppShell>
  );
}
