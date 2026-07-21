import { createFileRoute, Outlet, Link } from "@tanstack/react-router";
import { Building2, ShieldCheck, Sparkles } from "lucide-react";
import { BRAND, PORTAL_PRODUCT } from "@/lib/brand";

export const Route = createFileRoute("/_auth")({
  component: AuthLayout,
});

function AuthLayout() {
  return (
    <div className="relative flex min-h-screen w-full items-center justify-center overflow-hidden bg-background p-4 sm:p-6">
      <div className="pointer-events-none absolute inset-0 bg-aurora opacity-70" />
      <div className="pointer-events-none absolute inset-0 bg-grid opacity-[0.15]" />

      <div className="relative z-10 grid w-full max-w-6xl grid-cols-1 overflow-hidden rounded-2xl border border-border bg-card/70 shadow-elegant backdrop-blur lg:grid-cols-2">
        <div className="relative hidden flex-col justify-between overflow-hidden bg-gradient-to-br from-primary/20 via-background to-background p-10 lg:flex">
          <Link to="/dashboard" className="flex items-center gap-3">
            <img src={BRAND.markSvg} alt="" className="h-10 w-10 rounded-xl shadow-glow" draggable={false} />
            <div>
              <div className="font-display text-base font-bold">{PORTAL_PRODUCT}</div>
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground">{BRAND.tagline}</div>
            </div>
          </Link>

          <div className="max-w-md">
            <h2 className="font-display text-3xl font-semibold leading-tight text-gradient">
              Your cloud workspace for the entire MugoByte ecosystem.
            </h2>
            <p className="mt-3 text-sm text-muted-foreground">
              One secure login for businesses, products, licenses, devices, reports and future MugoByte apps — separate from live shop operations.
            </p>
            <ul className="mt-6 space-y-4 text-sm">
              {[
                { icon: Building2, title: "Multi-business workspace", desc: "Switch organizations; cloud data follows the selection." },
                { icon: ShieldCheck, title: "Shared identity & security", desc: "One account trusted across every MugoByte product." },
                { icon: Sparkles, title: "Product ecosystem", desc: "MBT POS today — Exam Hub, Farm, Trading, Media and more tomorrow." },
              ].map((item) => (
                <li key={item.title} className="flex gap-3 rounded-xl border border-border/60 bg-background/40 p-4">
                  <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
                    <item.icon className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="font-medium text-foreground">{item.title}</div>
                    <p className="mt-1 text-muted-foreground">{item.desc}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <p className="text-xs text-muted-foreground">© {new Date().getFullYear()} {BRAND.company} · portal.mugobyte.com</p>
        </div>

        <div className="flex items-center justify-center p-6 sm:p-10">
          <div className="w-full max-w-sm">
            <Link to="/dashboard" className="mb-8 flex items-center gap-2 lg:hidden">
              <img src={BRAND.markSvg} alt="" className="h-9 w-9 rounded-lg" draggable={false} />
              <div className="font-display text-sm font-bold">{PORTAL_PRODUCT}</div>
            </Link>
            <Outlet />
          </div>
        </div>
      </div>
    </div>
  );
}
