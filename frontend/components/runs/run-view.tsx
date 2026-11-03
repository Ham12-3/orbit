"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, MessageSquare } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { ErrorNote } from "@/components/error-note";
import { Markdown } from "@/components/markdown";
import { RunTimeline } from "@/components/run-timeline";
import { StatusBadge } from "@/components/status-badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { duration, timeAgo, tokens, usd } from "@/lib/format";
import { keys, useBotById, useCancelRun, useRun } from "@/lib/queries";
import { TERMINAL_STATUSES } from "@/lib/types";
import { useRunStream } from "@/lib/use-run-stream";
import { cn } from "@/lib/utils";

export function RunView() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const initial = useRun(id);
  const stream = useRunStream(id, (run) => {
    void queryClient.invalidateQueries({ queryKey: keys.run(id) });
    if (run) void queryClient.invalidateQueries({ queryKey: keys.botRuns(run.bot_id) });
  });
  // The stream replays every event from the start, so once it is connected it is the source.
  const run = stream.run ?? initial.data;
  const events = stream.run ? stream.events : (initial.data?.events ?? []);
  const bot = useBotById(run?.bot_id);

  if (initial.isError && !stream.run) return <ErrorNote error={initial.error} />;
  if (!run) return <Skeleton className="h-64 rounded-xl" />;

  const finished = TERMINAL_STATUSES.has(run.status);

  return (
    <div className="space-y-6">
      <Link
        href={bot.data ? `/bots/${bot.data.slug}?tab=runs` : "/bots"}
        className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2")}
      >
        <ArrowLeft /> {bot.data ? `${bot.data.avatar_emoji} ${bot.data.name}` : "Bots"}
      </Link>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Run</h1>
          <StatusBadge status={run.status} />
          <span className="text-sm text-muted-foreground">started {timeAgo(run.created_at)}</span>
        </div>
        {!finished && <CancelButton runId={run.id} />}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_260px]">
        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm text-muted-foreground">Task</CardTitle>
            </CardHeader>
            <CardContent className="text-sm whitespace-pre-wrap">{run.input_prompt}</CardContent>
          </Card>

          <section className="space-y-3">
            <h2 className="text-sm font-medium text-muted-foreground">Timeline</h2>
            {events.length === 0 && !finished && (
              <p className="text-sm text-muted-foreground">
                {run.status === "queued" ? "Waiting for the bot to be free…" : "Starting the bot's computer…"}
              </p>
            )}
            <RunTimeline events={events} live={!finished && events.length > 0} />
          </section>

          {finished && (run.final_summary || run.error) && (
            <Card className={cn(run.error && run.status !== "completed" && "ring-destructive/30")}>
              <CardHeader>
                <CardTitle className="text-sm text-muted-foreground">
                  {run.status === "completed" ? "Result" : "What went wrong"}
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm">
                {run.status === "completed" && run.final_summary ? (
                  <Markdown>{run.final_summary}</Markdown>
                ) : (
                  <p className="whitespace-pre-wrap text-destructive">{run.error}</p>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        <aside className="space-y-4">
          <Card size="sm">
            <CardContent className="space-y-2 text-sm">
              <Stat label="Cost">{usd(run.cost_usd)}</Stat>
              <Stat label="Input tokens">{tokens(run.input_tokens)}</Stat>
              <Stat label="Output tokens">{tokens(run.output_tokens)}</Stat>
              <Stat label="Cache read">{tokens(run.cache_read_tokens)}</Stat>
              <Stat label="Cache write">{tokens(run.cache_write_tokens)}</Stat>
              <Stat label="Turns">{run.num_turns ?? "–"}</Stat>
              <Stat label="Duration">{duration(run.started_at, run.finished_at)}</Stat>
            </CardContent>
          </Card>
          {run.thread_id && bot.data && (
            <Link
              href={`/bots/${bot.data.slug}?tab=chat&thread=${run.thread_id}`}
              className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-full")}
            >
              <MessageSquare /> Open the chat
            </Link>
          )}
          {stream.error && !finished && (
            <p className="text-xs text-muted-foreground">Live updates paused: {stream.error}. Retrying…</p>
          )}
        </aside>
      </div>
    </div>
  );
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="tabular-nums">{children}</span>
    </div>
  );
}

function CancelButton({ runId }: { runId: string }) {
  const cancel = useCancelRun();
  return (
    <AlertDialog>
      <AlertDialogTrigger className={buttonVariants({ variant: "outline" })} disabled={cancel.isPending}>
        {cancel.isPending ? "Cancelling…" : "Cancel run"}
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Cancel this run?</AlertDialogTitle>
          <AlertDialogDescription>
            The bot stops straight away. Files it already changed on its computer stay changed.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep running</AlertDialogCancel>
          <AlertDialogAction onClick={() => cancel.mutate(runId)}>Cancel run</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
