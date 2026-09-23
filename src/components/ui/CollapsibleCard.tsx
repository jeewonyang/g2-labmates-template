"use client";

import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { Card } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/**
 * A SectionCard whose body can be collapsed to just its header row.
 *
 * The open/closed state is per-browser (localStorage keyed by `storageKey`),
 * not per-user in the database: it is a viewing preference, and persisting it
 * server-side would make the desktop and a tablet fight over one row. Children
 * stay mounted while collapsed so a panel with its own client state — a feed
 * tab selection, an in-flight review — does not reset every time it is folded.
 */
export function CollapsibleSectionCard({
  title,
  action,
  children,
  className,
  bodyClassName,
  storageKey,
  defaultOpen = true,
}: {
  title: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  storageKey: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  // Read after mount rather than lazily in useState: the server render has no
  // localStorage, and seeding state from it directly would hydrate-mismatch.
  useEffect(() => {
    const stored = window.localStorage.getItem(`card-open:${storageKey}`);
    if (stored !== null) setOpen(stored === "1");
  }, [storageKey]);

  const toggle = () => {
    setOpen((current) => {
      window.localStorage.setItem(`card-open:${storageKey}`, current ? "0" : "1");
      return !current;
    });
  };

  return (
    <Card className={className}>
      <div className="flex items-center justify-between gap-2 border-b bg-[var(--surface-2)]/50 px-4 py-2.5">
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          className="-my-1 -ml-1 flex min-w-0 items-center gap-1.5 rounded px-1 py-1 text-left hover:bg-[var(--surface-hover)]"
        >
          <ChevronDown
            className={cn(
              "h-3.5 w-3.5 shrink-0 text-[var(--ink-3)] transition-transform",
              !open && "-rotate-90"
            )}
          />
          <h2 className="flex min-w-0 items-center gap-1.5 text-[13px] font-semibold tracking-wide text-[var(--ink)]">
            {title}
          </h2>
        </button>
        {action}
      </div>
      <div className={cn("p-4", !open && "hidden", bodyClassName)}>{children}</div>
    </Card>
  );
}
