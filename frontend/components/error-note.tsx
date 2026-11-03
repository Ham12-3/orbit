import { AlertTriangle } from "lucide-react";

import { ApiError } from "@/lib/api";

export function ErrorNote({ error }: { error: unknown }) {
  const message =
    error instanceof ApiError && error.status === 404
      ? "Not found. It may have been deleted, or it belongs to someone else."
      : error instanceof Error
        ? error.message
        : "Something went wrong.";
  return (
    <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span>{message}</span>
    </div>
  );
}
