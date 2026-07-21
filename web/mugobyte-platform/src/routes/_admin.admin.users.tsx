import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Users, RefreshCw, UserPlus, Trash2, ToggleLeft, ToggleRight } from "lucide-react";
import { toast } from "sonner";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { GET, POST, PUT } from "@/lib/api";

export const Route = createFileRoute("/_admin/admin/users")({
  component: AdminUsersPage,
  head: () => ({ meta: [{ title: "Users | MugoByte" }] }),
});

type User = {
  id: number;
  username: string;
  full_name?: string;
  email?: string;
  role: string;
  is_active: number;
  created_at?: string;
  last_login?: string;
};

const ROLE_COLORS: Record<string, string> = {
  superadmin: "destructive",
  admin: "default",
  manager: "secondary",
  cashier: "outline",
};

function AdminUsersPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [showInvite, setShowInvite] = useState(false);
  const [invite, setInvite] = useState({ username: "", full_name: "", email: "", role: "cashier", password: "" });

  const usersQ = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => GET<User[]>("/users"),
  });

  const createMut = useMutation({
    mutationFn: () => POST("/users", invite),
    onSuccess: () => {
      toast.success(`User @${invite.username} created`);
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      setShowInvite(false);
      setInvite({ username: "", full_name: "", email: "", role: "cashier", password: "" });
    },
    onError: () => toast.error("Failed to create user"),
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: number }) =>
      PUT(`/users/${id}`, { is_active }),
    onSuccess: () => {
      toast.success("User updated");
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: () => toast.error("Failed to update user"),
  });

  const users = Array.isArray(usersQ.data) ? usersQ.data : [];
  const filtered = q
    ? users.filter((u) =>
        (u.username || "").toLowerCase().includes(q.toLowerCase()) ||
        (u.full_name || "").toLowerCase().includes(q.toLowerCase()) ||
        (u.email || "").toLowerCase().includes(q.toLowerCase()),
      )
    : users;

  return (
    <PageShell>
      <PageHeader
        eyebrow="Admin"
        title="User Management"
        description="Create, manage and control access for every user across MBT POS and MugoByte Platform."
        actions={
          <>
            <Button variant="outline" onClick={() => usersQ.refetch()}><RefreshCw className="mr-1.5 h-4 w-4" />Refresh</Button>
            <Button onClick={() => setShowInvite((v) => !v)}><UserPlus className="mr-1.5 h-4 w-4" />Invite user</Button>
          </>
        }
      />

      {showInvite && (
        <Card className="border-primary/30 bg-primary/5">
          <CardHeader><CardTitle className="font-display text-base">New user</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {(["username", "full_name", "email", "password", "role"] as const).map((k) => (
                <div key={k} className="space-y-1.5">
                  <label className="text-sm font-medium capitalize">{k.replace(/_/g, " ")}</label>
                  <Input
                    type={k === "password" ? "password" : "text"}
                    value={invite[k]}
                    onChange={(e) => setInvite((f) => ({ ...f, [k]: e.target.value }))}
                    placeholder={k === "role" ? "cashier / manager / admin" : ""}
                  />
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <Button onClick={() => createMut.mutate()} disabled={createMut.isPending || !invite.username || !invite.password}>
                {createMut.isPending ? "Creating…" : "Create user"}
              </Button>
              <Button variant="outline" onClick={() => setShowInvite(false)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle className="font-display">All users</CardTitle>
              <CardDescription>{users.length} total · {users.filter((u) => u.is_active).length} active</CardDescription>
            </div>
            <Input className="h-9 w-60" placeholder="Search users…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {usersQ.isLoading ? (
            <div className="py-12 text-center text-sm text-muted-foreground">Loading users…</div>
          ) : usersQ.error ? (
            <div className="py-8 text-center text-sm text-destructive">Access denied or server error.</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>Username</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last login</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell>
                      <div className="font-medium">{u.full_name || u.username}</div>
                      <div className="text-xs text-muted-foreground">{u.email || "—"}</div>
                    </TableCell>
                    <TableCell className="font-mono text-sm">@{u.username}</TableCell>
                    <TableCell>
                      <Badge variant={ROLE_COLORS[u.role] as "default" | "secondary" | "destructive" | "outline" || "secondary"}>
                        {u.role}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={u.is_active ? "default" : "secondary"}>{u.is_active ? "Active" : "Disabled"}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{u.last_login?.slice(0, 16).replace("T", " ") || "Never"}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => toggleMut.mutate({ id: u.id, is_active: u.is_active ? 0 : 1 })}
                      >
                        {u.is_active ? <ToggleRight className="h-4 w-4 text-success" /> : <ToggleLeft className="h-4 w-4" />}
                        {u.is_active ? "Disable" : "Enable"}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
