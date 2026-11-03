"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";

import { ChatPanel } from "@/components/bots/chat-panel";
import { FilesPanel } from "@/components/bots/files-panel";
import { MemoryPanel } from "@/components/bots/memory-panel";
import { RunsPanel } from "@/components/bots/runs-panel";
import { SettingsPanel } from "@/components/bots/settings-panel";
import { ErrorNote } from "@/components/error-note";
import { StatusBadge } from "@/components/status-badge";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useBot } from "@/lib/queries";
import { MODELS } from "@/lib/types";
import { cn } from "@/lib/utils";

const LATER_TABS = [
  { value: "routines", label: "Routines", phase: 5, what: "Schedules and event triggers" },
];

export function BotView() {
  const { slug } = useParams<{ slug: string }>();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const bot = useBot(slug);
  const tab = searchParams.get("tab") ?? "chat";

  function setTab(value: string) {
    const params = new URLSearchParams(searchParams);
    params.set("tab", value);
    router.replace(`${pathname}?${params}`, { scroll: false });
  }

  if (bot.isPending) return <Skeleton className="h-64 rounded-xl" />;
  if (bot.isError) return <ErrorNote error={bot.error} />;

  return (
    <div className="space-y-6">
      <Link href="/bots" className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2")}>
        <ArrowLeft /> Bots
      </Link>
      <div className="flex items-start gap-4">
        <span className="text-4xl leading-none" aria-hidden>
          {bot.data.avatar_emoji}
        </span>
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-heading text-2xl font-semibold tracking-tight">{bot.data.name}</h1>
            <StatusBadge status={bot.data.status} />
          </div>
          <p className="text-sm text-muted-foreground">{bot.data.job_description}</p>
          <p className="text-xs text-muted-foreground">
            {MODELS[bot.data.model] ?? bot.data.model}
          </p>
        </div>
      </div>

      <Tabs value={tab} onValueChange={(value) => setTab(String(value))}>
        <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          <TabsList>
            <TabsTrigger value="chat">Chat</TabsTrigger>
            <TabsTrigger value="runs">Runs</TabsTrigger>
            {LATER_TABS.map((t) => (
              <TabsTrigger key={t.value} value={t.value}>
                {t.label}
              </TabsTrigger>
            ))}
            <TabsTrigger value="memory">Memory</TabsTrigger>
            <TabsTrigger value="files">Files</TabsTrigger>
            <TabsTrigger value="settings">Settings</TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="chat" className="pt-4">
          <ChatPanel bot={bot.data} />
        </TabsContent>
        <TabsContent value="runs" className="pt-4">
          <RunsPanel bot={bot.data} />
        </TabsContent>
        <TabsContent value="memory" className="pt-4">
          <MemoryPanel bot={bot.data} />
        </TabsContent>
        <TabsContent value="files" className="pt-4">
          <FilesPanel bot={bot.data} />
        </TabsContent>
        <TabsContent value="settings" className="pt-4">
          <SettingsPanel bot={bot.data} />
        </TabsContent>
        {LATER_TABS.map((t) => (
          <TabsContent key={t.value} value={t.value} className="pt-4">
            <div className="rounded-xl border border-dashed px-6 py-12 text-center">
              <p className="font-medium">{t.label} arrives in Phase {t.phase}</p>
              <p className="text-sm text-muted-foreground">{t.what}.</p>
            </div>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
