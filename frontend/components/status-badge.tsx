import { Badge } from "@/components/ui/badge";
import type { BotStatus, RunStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STYLES: Record<RunStatus | BotStatus, { label: string; className: string; live?: boolean }> = {
  queued: { label: "Queued", className: "bg-muted text-muted-foreground" },
  starting: { label: "Starting", className: "bg-sky-500/10 text-sky-700 dark:text-sky-300", live: true },
  running: { label: "Running", className: "bg-sky-500/10 text-sky-700 dark:text-sky-300", live: true },
  completed: { label: "Done", className: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" },
  failed: { label: "Failed", className: "bg-destructive/10 text-destructive" },
  timed_out: { label: "Timed out", className: "bg-destructive/10 text-destructive" },
  cancelled: { label: "Cancelled", className: "bg-muted text-muted-foreground" },
  idle: { label: "Idle", className: "bg-muted text-muted-foreground" },
  paused: { label: "Paused", className: "bg-amber-500/10 text-amber-700 dark:text-amber-300" },
  error: { label: "Error", className: "bg-destructive/10 text-destructive" },
};

export function StatusBadge({ status, className }: { status: RunStatus | BotStatus; className?: string }) {
  const style = STYLES[status];
  return (
    <Badge variant="secondary" className={cn("gap-1.5 border-transparent", style.className, className)}>
      {style.live && (
        <span className="relative flex size-1.5">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex size-1.5 rounded-full bg-current" />
        </span>
      )}
      {style.label}
    </Badge>
  );
}
