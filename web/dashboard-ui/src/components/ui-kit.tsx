import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
  as: As = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section";
}) {
  return (
    <As
      className={`rounded-xl border border-border bg-card shadow-card ${className}`}
    >
      {children}
    </As>
  );
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-[15px] font-semibold text-text">{children}</h2>
      {action}
    </div>
  );
}

export function Label({ children }: { children: ReactNode }) {
  return (
    <div className="text-[10px] tracking-[0.18em] font-semibold text-text2 uppercase">{children}</div>
  );
}

export function Badge({
  tone = "muted",
  children,
}: {
  tone?: "muted" | "ok" | "warn" | "err" | "info" | "gold";
  children: ReactNode;
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
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold ${map[tone]}`}
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
  size?: "sm" | "md" | "lg";
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const base =
    "inline-flex items-center justify-center gap-2 font-semibold transition-colors rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold/60 disabled:opacity-50";
  const sizes = {
    sm: "h-8 px-3 text-xs",
    md: "h-9 px-4 text-sm",
    lg: "h-11 px-5 text-[15px]",
  } as const;
  const variants = {
    primary: "bg-gold text-[color:var(--gold-fg)] hover:bg-gold-light shadow-[0_4px_14px_-4px_var(--gold)]",
    secondary: "bg-card text-text border border-border hover:bg-hover",
    ghost: "bg-transparent text-text hover:bg-hover",
    danger: "bg-err text-white hover:brightness-110",
    success: "bg-ok text-white hover:brightness-110",
  } as const;
  return (
    <button className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} {...rest}>
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`h-9 w-full rounded-md bg-input border border-border px-3 text-sm text-text placeholder:text-muted-fg focus:outline-none focus:border-gold/60 focus:ring-2 focus:ring-gold/25 ${props.className ?? ""}`}
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
      className={`h-9 rounded-md bg-input border border-border px-3 text-sm text-text focus:outline-none focus:border-gold/60 focus:ring-2 focus:ring-gold/25 ${rest.className ?? ""}`}
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
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "ok" | "warn" | "err" | "info" | "gold";
  icon: ReactNode;
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
    <div className="relative rounded-xl border border-border bg-card shadow-card overflow-hidden">
      <span className={`absolute left-0 top-0 bottom-0 w-[3px] ${bar}`} />
      <div className="p-3.5 sm:p-4 flex items-start gap-3">
        <div className={`h-10 w-10 rounded-full grid place-items-center shrink-0 ${iconBg}`}>
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[10px] tracking-[0.18em] font-semibold text-text2 uppercase truncate">
            {label}
          </div>
          <div
            className={`text-xl sm:text-2xl font-extrabold leading-tight mt-0.5 tabular-nums truncate ${valueColor}`}
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
}: {
  head: ReactNode[];
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto scrollbar-thin">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left">
            {head.map((h, i) => (
              <th
                key={i}
                className="px-4 py-2.5 text-[10px] tracking-[0.16em] font-semibold text-text2 uppercase border-b border-border bg-panel/40"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&>tr:nth-child(even)]:bg-panel/25 [&>tr]:border-b [&>tr]:border-border/60 [&>tr:hover]:bg-hover/50">
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
}: {
  children?: ReactNode;
  icon?: ReactNode;
  title?: string;
  description?: string;
}) {
  return (
    <div className="py-10 text-center text-sm text-text2">
      {icon ? <div className="mb-3 flex justify-center">{icon}</div> : null}
      {title ? <div className="text-text font-semibold mb-1">{title}</div> : null}
      {description ? <div className="text-text2">{description}</div> : null}
      {children}
    </div>
  );
}
