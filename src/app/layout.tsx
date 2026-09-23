import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/layout/AppShell";
import { countInbox } from "@/lib/services/capture";
import { getAutomationDashboard } from "@/lib/services/automation";
import { getHeartbeatStatus } from "@/lib/services/secondbrain";
import { getQueueStats } from "@/lib/services/ledger";

export const metadata: Metadata = {
  title: "G2",
  description: "A personal command center — projects, tasks, notes, and daily planning.",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [inboxCount, automation, heartbeat, queue] = await Promise.all([
    countInbox().catch(() => 0),
    getAutomationDashboard().catch(() => ({ active: 0, needsAttention: 0 })),
    getHeartbeatStatus(),
    getQueueStats().catch(() => ({ needsReview: 0 })),
  ]);
  const heartbeatAge = heartbeat.lastRun
    ? Date.now() - new Date(heartbeat.lastRun).getTime()
    : Number.POSITIVE_INFINITY;
  const pipelineHealth =
    automation.needsAttention > 0
      ? { label: "Needs attention", tone: "attention" as const }
      : automation.active > 0
        ? { label: "Processing", tone: "working" as const }
        : heartbeatAge < 36 * 60 * 60 * 1000
          ? { label: "Healthy", tone: "healthy" as const }
          : { label: "Local", tone: "local" as const };

  return (
    <html lang="en">
      <body className="antialiased">
        <AppShell
          inboxCount={inboxCount}
          reviewCount={queue.needsReview}
          pipelineHealth={pipelineHealth}
        >
          {children}
        </AppShell>
      </body>
    </html>
  );
}
