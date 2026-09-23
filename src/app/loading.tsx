export default function Loading() {
  return (
    <div className="animate-pulse space-y-4" role="status" aria-live="polite">
      <span className="sr-only">Loading page…</span>
      <div className="h-8 w-48 rounded bg-[var(--surface-2)]" />
      <div className="grid gap-3 sm:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-28 rounded-[var(--radius-card)] border bg-[var(--surface-2)]" />
        ))}
      </div>
    </div>
  );
}
