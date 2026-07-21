import { Link } from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { BRAND } from "@/lib/brand";

type BrandLogoProps = {
  /** Where the logo navigates. Portal: /dashboard. Live: /. */
  to: string;
  /** icon = mark only; wordmark = icon + text; full = HD logo image */
  variant?: "icon" | "wordmark" | "full";
  title?: string;
  subtitle?: string;
  collapsed?: boolean;
  className?: string;
  imgClassName?: string;
};

/**
 * Official clickable MugoByte logo.
 * Preserves SPA navigation (no full reload) and auth session.
 */
export function BrandLogo({
  to,
  variant = "wordmark",
  title = "MugoByte Workspace",
  subtitle = BRAND.tagline,
  collapsed = false,
  className,
  imgClassName,
}: BrandLogoProps) {
  if (variant === "full") {
    return (
      <Link
        to={to as "/dashboard"}
        className={cn(
          "brand-interactive inline-flex items-center outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background rounded-lg",
          className,
        )}
        aria-label={`${title} — go home`}
      >
        <img
          src={BRAND.logoHd}
          alt="MugoByte"
          className={cn("h-10 w-auto object-contain", imgClassName)}
          draggable={false}
        />
      </Link>
    );
  }

  return (
    <Link
      to={to as "/dashboard"}
      className={cn(
        "brand-interactive flex items-center gap-2.5 rounded-lg px-1 py-1 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        className,
      )}
      aria-label={`${title} — go home`}
    >
      <img
        src={BRAND.markSvg}
        alt=""
        className={cn(
          "h-9 w-9 shrink-0 rounded-lg object-cover shadow-sm ring-1 ring-border/60",
          imgClassName,
        )}
        draggable={false}
      />
      {!collapsed && variant === "wordmark" ? (
        <div className="min-w-0 text-left">
          <div className="font-display text-sm font-bold leading-tight truncate">{title}</div>
          {subtitle ? (
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground truncate">
              {subtitle}
            </div>
          ) : null}
        </div>
      ) : null}
    </Link>
  );
}
