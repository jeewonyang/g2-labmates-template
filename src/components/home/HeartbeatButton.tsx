"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Play, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/** Trigger an on-demand Admin scan+draft from the dashboard. */
export function HeartbeatButton({ className }: { className?: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function run() {
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch("/api/secondbrain/heartbeat", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        setMsg({ ok: false, text: data.detail || data.error || "Failed" });
      } else {
        setMsg({ ok: true, text: "Scan complete — check drafts below." });
        router.refresh();
      }
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {/*
        Named for what it looks at, not for the fact that it runs. This sweeps
        Gmail and read-state-independent Slack DMs, as opposed to "Process
        captures", which works on material already in
        the vault. Both used to be a play icon labelled "run".
      */}
      <Button
        onClick={run}
        disabled={busy}
        variant="secondary"
        size="sm"
        className={cn("w-full", className)}
        title="Scan Gmail and every new Slack DM, regardless of read state, then draft replies."
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
        {busy ? "Checking…" : "Check messages & calendar"}
      </Button>
      {msg && (
        <p
          role={msg.ok ? "status" : "alert"}
          aria-live={msg.ok ? "polite" : "assertive"}
          className={`mt-1.5 text-xs ${msg.ok ? "text-[var(--ink-3)]" : "text-[var(--red)]"}`}
        >
          {msg.text}
        </p>
      )}
    </div>
  );
}
