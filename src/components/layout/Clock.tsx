"use client";

import { useEffect, useState } from "react";
import { format } from "date-fns";

/**
 * Live clock for the header corner. Renders nothing until mounted so the
 * server and client markup never disagree (no hydration mismatch).
 */
export function Clock() {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div
      className="hidden min-w-[118px] text-right sm:block"
      aria-label="Current time"
    >
      {now && (
        <>
          <div className="font-mono text-sm font-semibold tabular-nums leading-tight text-[var(--ink)]">
            {format(now, "HH:mm:ss")}
          </div>
          <div className="font-mono text-[10px] uppercase tracking-[0.12em] leading-tight text-[var(--ink-3)]">
            {format(now, "EEE MMM d")}
          </div>
        </>
      )}
    </div>
  );
}
