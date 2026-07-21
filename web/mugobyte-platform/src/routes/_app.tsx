import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/layout/AppSidebar";
import { AppTopbar } from "@/components/layout/AppTopbar";
import { AppFooter } from "@/components/layout/AppFooter";
import { isAuthed } from "@/lib/api";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { pageTitle, PORTAL_PRODUCT } from "@/lib/brand";

export const Route = createFileRoute("/_app")({
  beforeLoad: () => {
    if (!isAuthed()) throw redirect({ to: "/login" });
  },
  component: AppLayout,
});

function AppLayout() {
  useDocumentTitle(pageTitle(PORTAL_PRODUCT));
  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full bg-background">
        <AppSidebar variant="customer" />
        <SidebarInset className="flex min-w-0 flex-1 flex-col">
          <AppTopbar />
          <main className="min-w-0 flex-1">
            <Outlet />
          </main>
          <AppFooter />
        </SidebarInset>
      </div>
    </SidebarProvider>
  );
}
