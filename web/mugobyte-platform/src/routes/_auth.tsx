import { createFileRoute, Outlet, Link } from "@tanstack/react-router";
import { Building2, ShieldCheck, Sparkles } from "lucide-react";
import { BRAND, PORTAL_PRODUCT } from "@/lib/brand";
import { useTheme } from "@/lib/theme";

export const Route = createFileRoute("/_auth")({
  component: AuthLayout,
});

function AuthBrandMark({ className }: { className?: string }) {
  const { theme } = useTheme();
  const isDark =
    theme === "dark" ||
    (theme === "system" &&
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  const src = isDark ? BRAND.companyLogoDark : BRAND.companyLogo;
  const srcSet = isDark
    ? `${BRAND.companyLogoDark} 1x, ${BRAND.companyLogoDark2x} 2x`
    : `${BRAND.companyLogo} 1x, ${BRAND.companyLogo2x} 2x`;
  return (
    <img
      src={src}
      srcSet={srcSet}
      alt="MugoByte Technologies"
      className={className}
      draggable={false}
    />
  );
}

function AuthLayout() {
  return (
    <div className="relative flex min-h-screen w-full items-center justify-center overflow-hidden bg-background p-4 sm:p-6">
      <div className="pointer-events-none absolute inset-0 bg-aurora opacity-70" />
      <div className="pointer-events-none absolute inset-0 bg-grid opacity-[0.15]" />

      <div className="relative z-10 grid w-full max-w-6xl grid-cols-1 overflow-hidden rounded-2xl border border-border bg-card/70 shadow-elegant backdrop-blur lg:grid-cols-2">
        <div className="relative hidden flex-col justify-between overflow-hidden bg-gradient-to-br from-primary/20 via-background to-background p-10 lg:flex">
          <Link to="/dashboard" className="inline-flex max-w-[240px]" aria-label={`${PORTAL_PRODUCT} home`}>
            <AuthBrandMark className="h-11 w-auto max-w-full object-contain object-left" />
          </Link>

          <div className="max-w-md">
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">
              {PORTAL_PRODUCT}
            </p>
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
                <li
                  key={item.title}
                  className="flex gap-3 rounded-xl border border-border/60 bg-background/40 p-4 transition-colors hover:border-primary/30 hover:bg-background/55"
                >
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

          <p className="text-xs text-muted-foreground">
            © {new Date().getFullYear()} {BRAND.company} · portal.mugobyte.com
          </p>
        </div>

        <div className="flex items-center justify-center p-6 sm:p-10">
          <div className="w-full max-w-sm">
            <Link to="/dashboard" className="mb-8 inline-flex max-w-[200px] lg:hidden" aria-label={PORTAL_PRODUCT}>
              <AuthBrandMark className="h-10 w-auto object-contain object-left" />
            </Link>
            <Outlet />
          </div>
        </div>
      </div>
    </div>
  );
}
