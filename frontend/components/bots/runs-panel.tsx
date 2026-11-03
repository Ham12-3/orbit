"use client";

import { Play } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ErrorNote } from "@/components/error-note";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { duration, timeAgo, usd } from "@/lib/format";
import { useBotRuns, useStartRun } from "@/lib/queries";
import type { Bot, RunTrigger } from "@/lib/types";

const TRIGGERS: Record<RunTrigger, string> = {
  manual: "Task",
  chat: "Chat",
  schedule: "Schedule",
  event: "Event",
  handoff: "Handoff",
  approval_followup: "Approval",
};

export function RunsPanel({ bot }: { bot: Bot }) {
  const router = useRouter();
  const runs = useBotRuns(bot.id);
  const startRun = useStartRun(bot.id);
  const [prompt, setPrompt] = useState("");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const run = await startRun.mutateAsync(prompt.trim());
    router.push(`/runs/${run.id}`);
  }

  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} className="space-y-3 rounded-xl border p-4">
        <label htmlFor="task" className="text-sm font-medium">
          Give {bot.name} a task
        </label>
        <Textarea
          id="task"
          rows={3}
          maxLength={20000}
          placeholder="Create workspace/hello.txt containing today's date, then tell me what you did."
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />
        {startRun.isError && <ErrorNote error={startRun.error} />}
        <div className="flex justify-end">
          <Button type="submit" disabled={!prompt.trim() || startRun.isPending}>
            <Play /> {startRun.isPending ? "Starting…" : "Run"}
          </Button>
        </div>
      </form>

      {runs.isPending && <Skeleton className="h-40 rounded-xl" />}
      {runs.isError && <ErrorNote error={runs.error} />}
      {runs.data?.length === 0 && (
        <p className="py-8 text-center text-sm text-muted-foreground">No runs yet.</p>
      )}
      {runs.data && runs.data.length > 0 && (
        <ul className="divide-y rounded-xl border">
          {runs.data.map((run) => (
            <li key={run.id}>
              <Link
                href={`/runs/${run.id}`}
                className="flex flex-col gap-1 px-4 py-3 transition-colors hover:bg-muted/40 sm:flex-row sm:items-center sm:gap-4"
              >
                <div className="flex shrink-0 items-center gap-2">
                  <StatusBadge status={run.status} />
                  <span className="text-xs text-muted-foreground">{TRIGGERS[run.trigger_type]}</span>
                </div>
                <span className="min-w-0 flex-1 truncate text-sm">{run.input_prompt}</span>
                <span className="flex shrink-0 gap-3 text-xs text-muted-foreground tabular-nums">
                  <span>{timeAgo(run.created_at)}</span>
                  <span>{duration(run.started_at, run.finished_at)}</span>
                  <span>{usd(run.cost_usd)}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
