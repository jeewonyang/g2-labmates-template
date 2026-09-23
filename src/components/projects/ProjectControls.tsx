"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { setNextActionAction, setProjectStatusAction } from "@/lib/actions";
import { Select } from "@/components/ui/inputs";
import { PROJECT_STATUSES, PROJECT_STATUS_META } from "@/lib/types";

export function ProjectStatusSelect({ id, status }: { id: string; status: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <Select
      value={status}
      disabled={pending}
      onChange={(e) =>
        start(async () => {
          await setProjectStatusAction(id, e.target.value);
          router.refresh();
        })
      }
      className="h-8 w-auto py-1 text-xs"
      aria-label="Project status"
    >
      {PROJECT_STATUSES.map((s) => (
        <option key={s} value={s}>{PROJECT_STATUS_META[s].label}</option>
      ))}
    </Select>
  );
}

export function NextActionSelect({
  projectId,
  currentId,
  tasks,
}: {
  projectId: string;
  currentId: string | null;
  tasks: { id: string; title: string; status: string }[];
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const open = tasks.filter((t) => t.status !== "completed" && t.status !== "canceled");
  return (
    <Select
      value={currentId ?? ""}
      disabled={pending}
      onChange={(e) =>
        start(async () => {
          await setNextActionAction(projectId, e.target.value || null);
          router.refresh();
        })
      }
      className="h-8 py-1 text-xs"
      aria-label="Next action"
    >
      <option value="">— Pick next action —</option>
      {open.map((t) => (
        <option key={t.id} value={t.id}>{t.title}</option>
      ))}
    </Select>
  );
}
