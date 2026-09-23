"use client";

import { cn } from "@/lib/utils";

const FIELD =
  "w-full rounded-[var(--radius-sm)] border bg-[var(--surface)] px-3 py-2 text-sm text-[var(--ink)] placeholder:text-[var(--ink-3)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn(FIELD, props.className)} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(FIELD, "resize-y", props.className)} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cn(FIELD, "appearance-none pr-8", props.className)} />;
}

export function Field({
  label,
  htmlFor,
  children,
  className,
  style,
}: {
  label: string;
  htmlFor?: string;
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <label htmlFor={htmlFor} className={cn("block", className)} style={style}>
      <span className="mb-1 block text-xs font-medium text-[var(--ink-2)]">{label}</span>
      {children}
    </label>
  );
}

/**
 * Date picker with an optional time-of-day. Uses inline styles for the flex
 * layout (spanning the full form width, flexible date + fixed-width time)
 * rather than Tailwind utilities: in this Tailwind v4 setup the arbitrary/
 * layout classes (col-span-2, flex-1, basis-32) don't reliably generate, and
 * without them the time box renders full-width and overlaps the dialog.
 */
export function DateTimeField({
  label,
  date,
  time,
  onChange,
  className,
}: {
  label: string;
  date: string;
  time: string;
  onChange: (date: string, time: string) => void;
  className?: string;
}) {
  return (
    <Field label={label} className={className} style={{ gridColumn: "1 / -1" }}>
      <div style={{ display: "flex", gap: "8px", width: "100%" }}>
        <Input
          type="date"
          style={{ flex: "1 1 0%", minWidth: 0, width: "auto" }}
          value={date}
          onChange={(e) => onChange(e.target.value, time)}
        />
        <Input
          type="time"
          aria-label={`${label} time (optional)`}
          style={{ flex: "0 0 8rem", minWidth: 0, width: "auto" }}
          value={time}
          disabled={!date}
          onChange={(e) => onChange(date, e.target.value)}
        />
      </div>
    </Field>
  );
}
