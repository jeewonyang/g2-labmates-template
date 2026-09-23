"use client";

import { useCallback, useEffect, useState } from "react";

function friendlyActionError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error ?? "");

  if (/at most 300 character|maximum.?300|too_big/i.test(message)) {
    return "Title must be 300 characters or fewer.";
  }
  if (/invalid url|valid url/i.test(message)) {
    return "Enter a complete URL, including https://.";
  }
  if (/network|fetch|connection|timeout|timed out/i.test(message)) {
    return "The service could not be reached. Your input is still here; try again.";
  }

  return "Could not save your changes. Check the fields and try again.";
}

/** Keep expected validation/service failures inside the open form. */
export function useFormActionError(open: boolean) {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) setError(null);
  }, [open]);

  const run = useCallback(async (work: () => Promise<void>) => {
    setError(null);
    try {
      await work();
    } catch (caught) {
      setError(friendlyActionError(caught));
    }
  }, []);

  return { error, run };
}
