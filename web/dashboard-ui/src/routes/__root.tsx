import { Outlet, Link, createRootRouteWithContext } from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";
import { AuthGate } from "@/lib/auth";

function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-app px-4">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-extrabold text-gold">404</h1>
        <h2 className="mt-4 text-xl font-semibold text-text">Page not found</h2>
        <Link
          to="/"
          className="mt-6 inline-flex rounded-md bg-gold px-4 py-2 text-sm font-semibold text-[color:var(--gold-fg)]"
        >
          Back to Dashboard
        </Link>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: () => (
    <AuthGate>
      <Outlet />
    </AuthGate>
  ),
  notFoundComponent: NotFound,
});
