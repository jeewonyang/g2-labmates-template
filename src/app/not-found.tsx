import { LinkButton } from "@/components/ui/primitives";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center rounded-[var(--radius-card)] border border-dashed px-6 py-16 text-center">
      <p className="text-4xl font-bold text-[var(--ink-3)]">404</p>
      <h2 className="mt-2 text-lg font-semibold text-[var(--ink)]">Not found</h2>
      <p className="mt-1 text-sm text-[var(--ink-3)]">That item doesn&apos;t exist or was archived.</p>
      <LinkButton href="/today" variant="primary" className="mt-4">Go to Today</LinkButton>
    </div>
  );
}
