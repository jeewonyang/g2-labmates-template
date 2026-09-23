"use client";

import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/primitives";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[var(--radius-card)] border border-dashed px-6 py-16 text-center">
      <AlertTriangle className="mb-3 h-8 w-8 text-[var(--amber)]" />
      <h2 className="text-lg font-semibold text-[var(--ink)]">Something went wrong</h2>
      <p className="mt-1 max-w-md text-sm text-[var(--ink-3)]">
        {error.message || "An unexpected error occurred while loading this page."}
      </p>
      <Button variant="primary" className="mt-4" onClick={reset}>
        Try again
      </Button>
    </div>
  );
}
