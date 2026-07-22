import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/layout/AppSidebar";
import { AppTopbar } from "@/components/layout/AppTopbar";
import { ensureAuthSession, isPlatformAdmin } from "@/lib/api";

export const Route = createFileRoute("/_admin")({
  beforeLoad: async ({ location }) => {
    const ok = await ensureAuthSession();
    if (!ok) {
      const next = `${location.pathname}${location.search || ""}`;
      throw redirect({
        to: "/login",
        search: { redirect: next },
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
