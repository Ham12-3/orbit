"use client";

import { Plus } from "lucide-react";
import Link from "next/link";

import { ErrorNote } from "@/components/error-note";
import { StatusBadge } from "@/components/status-badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { timeAgo, usd } from "@/lib/format";
import { useBots } from "@/lib/queries";
import type { Bot } from "@/lib/types";

export function BotsGrid() {
  const bots = useBots();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Bots</h1>
          <p className="text-sm text-muted-foreground">Each bot has its own computer and its own job.</p>
        </div>
        <Link href="/bots/new" className={buttonVariants()}>
          <Plus /> New bot
        </Link>
      </div>

      {bots.isPending && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))}
        </div>
      )}
      {bots.isError && <ErrorNote error={bots.error} />}
      {bots.data?.length === 0 && <EmptyState />}
      {bots.data && bots.data.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {bots.data.map((bot) => (
            <BotCard key={bot.id} bot={bot} />
          ))}
        </div>
      )}
    </div>
  );
}

function BotCard({ bot }: { bot: Bot }) {
  return (
    <Link href={`/bots/${bot.slug}`} className="group rounded-xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
      <Card className="h-full transition-colors group-hover:bg-muted/40">
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <span className="text-3xl leading-none" aria-hidden>
              {bot.avatar_emoji}
            </span>
            <StatusBadge status={bot.status} />
          </div>
          <CardTitle className="pt-2">{bot.name}</CardTitle>
          <CardDescription className="line-clamp-2">{bot.job_description}</CardDescription>
        </CardHeader>
        <CardContent className="mt-auto flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {bot.last_run_at ? `Last run ${timeAgo(bot.last_run_at)}` : "No runs yet"}
          </span>
          <span title="Spent today (UTC)">{usd(bot.cost_today_usd)} today</span>
        </CardContent>
      </Card>
    </Link>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center gap-4 rounded-xl border border-dashed px-6 py-16 text-center">
      <span className="text-4xl" aria-hidden>
        🤖
      </span>
      <div className="space-y-1">
        <p className="font-medium">No bots yet</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          Give a bot a name and a job. It gets its own cloud computer and works even when your laptop
          is closed.
        </p>
      </div>
      <Link href="/bots/new" className={buttonVariants()}>
        <Plus /> Create your first bot
      </Link>
    </div>
  );
}
