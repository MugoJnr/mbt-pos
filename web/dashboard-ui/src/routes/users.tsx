import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { Badge, Card, Table } from "@/components/ui-kit";
import { GET } from "@/lib/api";

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
  const usersQ = useQuery({
    queryKey: ["users"],
    queryFn: () => GET<any[]>("/users"),
  });
  const users = Array.isArray(usersQ.data) ? usersQ.data : [];
  const err = usersQ.data && !Array.isArray(usersQ.data) ? (usersQ.data as any).error : null;

  return (
    <AppShell title="Users & Access">
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-text2 max-w-2xl">
          Staff accounts and roles from the POS database. Create/edit users from the desktop app
          or legacy tools if needed.
        </p>
      </div>

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
