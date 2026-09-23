"use client";

import { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Copy text to the clipboard, with the confirmation inline on the button.
 *
 * The label swaps to "Copied" for two seconds rather than pushing a message
 * into the layout — a status line appearing under a row reflows everything
 * below it, which is exactly the twitchiness a dense dashboard should avoid.
 */
export function CopyButton({
  text,
  label = "Copy",
  copiedLabel = "Copied",
  className,
  title,
}: {
  text: string;
  label?: string;
  copiedLabel?: string;
  className?: string;
  title?: string;
}) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!copied && !failed) return;
    const t = window.setTimeout(() => {
      setCopied(false);
      setFailed(false);
    }, 2000);
    return () => window.clearTimeout(t);
  }, [copied, failed]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      // Clipboard access needs a secure context. Over plain http on the
      // tailnet (your-machine:3000) it is unavailable, so say so rather than
      // silently doing nothing.
      setFailed(true);
    }
  }

  return (
    <button
      onClick={copy}
      disabled={!text}
      title={title ?? (text ? "Copy to clipboard" : "Nothing to copy")}
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-[var(--radius-sm)] border px-2 py-1 text-xs font-medium text-[var(--ink-2)] transition-colors hover:bg-[var(--surface-hover)] disabled:opacity-40",
        copied && "border-[var(--green)]/40 text-[var(--green)]",
        failed && "border-[var(--red)]/40 text-[var(--red)]",
        className,
      )}
    >
      {copied ? (
        <Check className="h-3.5 w-3.5" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
      {failed ? "Blocked" : copied ? copiedLabel : label}
    </button>
  );
}
