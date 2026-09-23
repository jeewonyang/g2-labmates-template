import Link from "next/link";
import { cn } from "@/lib/utils";

/** Surface card. `as="section"`-ish; keep it a div for flexibility. */
export function Card({
  children,
  className,
  interactive = false,
}: {
  children: React.ReactNode;
  className?: string;
  interactive?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-card)] border bg-[var(--surface)] shadow-[var(--shadow-sm)]",
        interactive &&
          "transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)]",
        className
      )}
    >
      {children}
    </div>
  );
}

export function SectionCard({
  title,
  action,
  children,
  className,
  bodyClassName,
}: {
  title: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <Card className={className}>
      <div className="flex items-center justify-between gap-2 border-b bg-[var(--surface-2)]/50 px-4 py-2.5">
        <h2 className="flex items-center gap-1.5 text-[13px] font-semibold tracking-wide text-[var(--ink)]">
          {title}
        </h2>
        {action}
      </div>
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </Card>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-[var(--ink)]">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-[var(--ink-2)]">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[var(--radius-card)] border border-dashed px-6 py-10 text-center">
      {icon && <div className="mb-3 text-[var(--ink-3)]">{icon}</div>}
      <p className="text-sm font-medium text-[var(--ink)]">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-[var(--ink-3)]">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ProgressBar({ value }: { value: number | null }) {
  const pct = value == null ? 0 : Math.round(value * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--gray-soft)]">
        <div
          className="h-full rounded-full bg-gradient-to-r from-[var(--accent)] to-[var(--cyan)] transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-9 text-right font-mono text-xs tabular-nums text-[var(--ink-3)]">
        {value == null ? "—" : `${pct}%`}
      </span>
    </div>
  );
}

type ButtonProps = {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  className?: string;
} & React.ButtonHTMLAttributes<HTMLButtonElement>;

const BTN_BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-sm)] font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--bg)]";

const BTN_VARIANT = {
  primary: "bg-[var(--accent)] text-white shadow-[var(--glow-accent)] hover:opacity-90",
  secondary:
    "border bg-[var(--surface)] text-[var(--ink)] hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)]",
  ghost: "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]",
  danger: "border border-[var(--red)] text-[var(--red)] hover:bg-[var(--red-soft)]",
};

const BTN_SIZE = { sm: "h-8 px-3 text-xs", md: "h-9 px-4 text-sm" };

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ButtonProps) {
  return (
    <button className={cn(BTN_BASE, BTN_VARIANT[variant], BTN_SIZE[size], className)} {...props} />
  );
}

export function LinkButton({
  href,
  variant = "secondary",
  size = "md",
  className,
  children,
}: {
  href: string;
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md";
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link href={href} className={cn(BTN_BASE, BTN_VARIANT[variant], BTN_SIZE[size], className)}>
      {children}
    </Link>
  );
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-[var(--radius-card)] border bg-[var(--surface)] px-4 py-3 shadow-[var(--shadow-sm)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)]">
      <div className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--ink-3)]">
        {label}
      </div>
      <div className="mt-1 font-mono text-2xl font-bold tabular-nums text-[var(--ink)]">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-[var(--ink-3)]">{hint}</div>}
    </div>
  );
}
