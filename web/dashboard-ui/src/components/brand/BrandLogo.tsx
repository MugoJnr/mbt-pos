import { Link } from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { BRAND } from "@/lib/brand";

type BrandLogoProps = {
  /** Live Dashboard home for this shop — never Portal. */
  to?: string;
  variant?: "icon" | "wordmark" | "full";
  title?: string;
  subtitle?: string;
  className?: string;
  imgClassName?: string;
};

/**
 * Official clickable MugoByte logo for Live Dashboard.
 * Always returns to Live Dashboard home — never Portal.
 */
export function BrandLogo({
  to = "/",
  variant = "wordmark",
  title = "MBT POS",
  subtitle = "Live Dashboard",
  className,
  imgClassName,
}: BrandLogoProps) {
  if (variant === "full") {
    return (
      <Link
        to={to}
        className={cn(
          "brand-interactive inline-flex items-center outline-none focus-visible:ring-2 focus-visible:ring-gold/50 rounded-lg",
          className,
        )}
        aria-label={`${title} — Dashboard home`}
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
      to={to}
      className={cn(
        "brand-interactive flex items-center gap-3 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-gold/50",
        className,
      )}
      aria-label={`${title} — Dashboard home`}
    >
      <img
        src={BRAND.icon}
        alt=""
        className={cn(
          "h-11 w-11 shrink-0 rounded-xl object-cover shadow-gold ring-1 ring-border",
          imgClassName,
        )}
        draggable={false}
      />
      {variant === "wordmark" ? (
        <div className="leading-tight min-w-0 text-left">
          <div className="font-display font-extrabold text-gold text-lg tracking-wide truncate">
            {title}
          </div>
          <div className="text-eyebrow text-text2 truncate">{subtitle}</div>
        </div>
      ) : null}
    </Link>
  );
}
