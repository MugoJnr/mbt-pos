import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Card({
  children,
  className = "",
  as: As = "div",
  padded = false,
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section";
  padded?: boolean;
}) {
  return (
    <As
      className={cn(
        "rounded-xl border border-border bg-card shadow-card transition-ui",
        padded && "p-4 sm:p-5",
        className,
      )}
    >
      {children}
    </As>
  );
}

export function PageHeader({
  title,
  description,
  icon,
  actions,
  eyebrow,
  className = "",
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  actions?: ReactNode;
  eyebrow?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col sm:flex-row sm:items-start justify-between gap-3 mb-5",
        className,
      )}
    >
      <div className="min-w-0">
        {eyebrow ? <div className="text-eyebrow mb-1">{eyebrow}</div> : null}
        <h2 className="text-title text-text flex items-center gap-2.5">
          {icon ? (
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-gold/12 text-gold shrink-0">
              {icon}
            </span>
          ) : null}
          <span className="truncate">{title}</span>
        </h2>
        {description ? <p className="text-sm text-text2 mt-1 max-w-2xl">{description}</p> : null}
      </div>
      {actions ? (
        <div className="flex flex-wrap items-center gap-2 shrink-0">{actions}</div>
      ) : null}
    </div>
  );
}

export function SectionTitle({
  children,
  action,
  className = "",
}: {
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between mb-3 gap-2", className)}>
      <h3 className="text-[15px] font-semibold text-text tracking-tight">{children}</h3>
      {action}
    </div>
  );
}

export function Label({ children }: { children: ReactNode }) {
  return <div className="text-eyebrow">{children}</div>;
}

export function Badge({
  tone = "muted",
  children,
  className = "",
}: {
  tone?: "muted" | "ok" | "warn" | "err" | "info" | "gold";
  children: ReactNode;
  className?: string;
}) {
  const map = {
    muted: "bg-panel text-text2 border-border",
    ok: "bg-ok/15 text-ok border-ok/30",
    warn: "bg-warn/15 text-warn border-warn/30",
    err: "bg-err/15 text-err border-err/30",
    info: "bg-info/15 text-info border-info/30",
    gold: "bg-gold/15 text-gold border-gold/30",
  } as const;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide",
        map[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  children,
  ...rest
}: {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "success";
  size?: "sm" | "md" | "lg" | "touch";
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const base =
    "inline-flex items-center justify-center gap-2 font-semibold transition-ui rounded-lg focus-visible:outline-none disabled:opacity-50 disabled:pointer-events-none active:scale-[0.98]";
  const sizes = {
    sm: "h-8 px-3 text-xs rounded-md",
    md: "h-9 px-4 text-sm",
    lg: "h-11 px-5 text-[15px]",
    touch: "min-h-[44px] px-5 text-[15px]",
  } as const;
  const variants = {
    primary:
      "bg-gold text-[color:var(--gold-fg)] hover:bg-gold-light shadow-gold",
    secondary: "bg-card text-text border border-border hover:bg-hover hover:border-border2",
    ghost: "bg-transparent text-text hover:bg-hover",
    danger: "bg-err text-white hover:brightness-110",
    success: "bg-ok text-white hover:brightness-110",
  } as const;
  return (
    <button className={cn(base, sizes[size], variants[variant], className)} {...rest}>
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        "h-9 w-full rounded-lg bg-input border border-border px-3 text-sm text-text placeholder:text-muted-fg transition-ui focus:outline-none focus:border-gold/60 focus:ring-2 focus:ring-gold/25",
        props.className,
      )}
    />
  );
}

export function Select({
  children,
  ...rest
}: React.SelectHTMLAttributes<HTMLSelectElement> & { children: ReactNode }) {
  return (
    <select
      {...rest}
      className={cn(
        "h-9 rounded-lg bg-input border border-border px-3 text-sm text-text transition-ui focus:outline-none focus:border-gold/60 focus:ring-2 focus:ring-gold/25",
        rest.className,
      )}
    >
      {children}
    </select>
  );
}

export function KpiCard({
  label,
  value,
  sub = "",
  accent = "gold",
  icon,
  className = "",
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "ok" | "warn" | "err" | "info" | "gold";
  icon: ReactNode;
  className?: string;
}) {
  const bar = {
    ok: "bg-ok",
    warn: "bg-warn",
    err: "bg-err",
    info: "bg-info",
    gold: "bg-gold",
  }[accent];
  const iconBg = {
    ok: "bg-ok/15 text-ok",
    warn: "bg-warn/15 text-warn",
    err: "bg-err/15 text-err",
    info: "bg-info/15 text-info",
    gold: "bg-gold/15 text-gold",
  }[accent];
  const valueColor = {
    ok: "text-ok",
    warn: "text-warn",
    err: "text-err",
    info: "text-info",
    gold: "text-gold",
  }[accent];
  return (
    <div
      className={cn(
        "relative rounded-xl border border-border bg-card shadow-card overflow-hidden group hover:border-gold/25 transition-ui",
        className,
      )}
    >
      <span className={cn("absolute left-0 top-0 bottom-0 w-[3px]", bar)} />
      <div className="absolute inset-0 bg-gradient-to-br from-transparent via-transparent to-gold/[0.03] pointer-events-none" />
      <div className="relative p-3.5 sm:p-4 flex items-start gap-3">
        <div
          className={cn(
            "h-10 w-10 rounded-xl grid place-items-center shrink-0 transition-ui group-hover:scale-105",
            iconBg,
          )}
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-eyebrow truncate">{label}</div>
          <div
            className={cn(
              "text-xl sm:text-2xl font-extrabold leading-tight mt-0.5 tabular-nums truncate tracking-tight",
              valueColor,
            )}
          >
            {value}
          </div>
          {sub ? <div className="text-xs text-text2 mt-0.5 truncate">{sub}</div> : null}
        </div>
      </div>
    </div>
  );
}

export function Table({
  head,
  children,
  sticky = true,
}: {
  head: ReactNode[];
  children: ReactNode;
  sticky?: boolean;
}) {
  return (
    <div className="overflow-x-auto scrollbar-thin">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left">
            {head.map((h, i) => (
              <th
                key={i}
                className={cn(
                  "px-4 py-3 text-eyebrow border-b border-border bg-panel/50",
                  sticky && "sticky top-0 z-[1]",
                )}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&>tr:nth-child(even)]:bg-panel/20 [&>tr]:border-b [&>tr]:border-border/50 [&>tr]:transition-colors [&>tr:hover]:bg-hover/40">
          {children}
        </tbody>
      </table>
    </div>
  );
}

export function EmptyState({
  children,
  icon,
  title,
  description,
  className = "",
}: {
  children?: ReactNode;
  icon?: ReactNode;
  title?: string;
  description?: string;
  className?: string;
}) {
  return (
    <div className={cn("py-12 px-4 text-center text-sm text-text2", className)}>
      {icon ? (
        <div className="mb-3 flex justify-center">
          <div className="h-12 w-12 rounded-2xl bg-panel border border-border grid place-items-center text-muted-fg">
            {icon}
          </div>
        </div>
      ) : null}
      {title ? <div className="text-text font-semibold text-[15px] mb-1">{title}</div> : null}
      {description ? <div className="text-text2 max-w-sm mx-auto">{description}</div> : null}
      {children ? <div className="mt-4">{children}</div> : null}
    </div>
  );
}

export function Skeleton({
  className = "",
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return <div className={cn("skeleton", className)} style={style} aria-hidden />;
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <Card className="p-4 space-y-3">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="h-7 w-36" />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className="h-3 w-full" style={{ opacity: 1 - i * 0.15 }} />
      ))}
    </Card>
  );
}
