import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/layout/AppSidebar";
import { AppTopbar } from "@/components/layout/AppTopbar";
import { ensureAuthSession, isPlatformAdmin } from "@/lib/api";

export const Route = createFileRoute("/_admin")({
  beforeLoad: async ({ location }) => {
    // A rejected bootstrap (offline, 5xx) must land on sign-in, not the error
    // boundary. `location.search` is a parsed object, so build the return
    // target from `href`.
    const ok = await ensureAuthSession().catch(() => false);
    if (!ok) {
      throw redirect({
        to: "/login",
        search: { redirect: location.href || "/admin" },
      });
    }
    if (!isPlatformAdmin()) throw redirect({ to: "/dashboard" });
  },
  component: AdminLayout,
});

function AdminLayout() {
  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full bg-background">
        <AppSidebar variant="admin" />
        <SidebarInset className="min-w-0 flex-1">
          <AppTopbar />
          <main className="min-w-0 flex-1">
            <Outlet />
          </main>
        </SidebarInset>
      </div>
    </SidebarProvider>
  );
}
