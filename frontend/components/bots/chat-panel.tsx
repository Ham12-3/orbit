"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowUp, ExternalLink, MessageSquarePlus } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { ErrorNote } from "@/components/error-note";
import { Markdown } from "@/components/markdown";
import { RunTimeline } from "@/components/run-timeline";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { timeAgo } from "@/lib/format";
import { keys, useCancelRun, useCreateThread, usePostMessage, useThread, useThreads } from "@/lib/queries";
import type { Bot, Message, RunEvent } from "@/lib/types";
import { useRunStream } from "@/lib/use-run-stream";
import { cn } from "@/lib/utils";

export function ChatPanel({ bot }: { bot: Bot }) {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const threadId = searchParams.get("thread");
  const threads = useThreads(bot.id);

  function selectThread(id: string | null) {
    const params = new URLSearchParams(searchParams);
    params.set("tab", "chat");
    if (id) params.set("thread", id);
    else params.delete("thread");
    router.replace(`${pathname}?${params}`, { scroll: false });
  }

  return (
    <div className="grid gap-6 md:grid-cols-[240px_1fr]">
      <aside className={cn("space-y-2", threadId && "hidden md:block")}>
        <Button variant="outline" className="w-full justify-start" onClick={() => selectThread(null)}>
          <MessageSquarePlus /> New chat
        </Button>
        {threads.isPending && <Skeleton className="h-24" />}
        <nav className="space-y-0.5">
          {threads.data?.map((thread) => (
            <button
              key={thread.id}
              type="button"
              onClick={() => selectThread(thread.id)}
              className={cn(
                "w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted",
                thread.id === threadId && "bg-muted",
              )}
            >
              <span className="block truncate text-sm">{thread.title}</span>
              <span className="text-xs text-muted-foreground">{timeAgo(thread.updated_at)}</span>
            </button>
          ))}
        </nav>
      </aside>
      <section className="min-w-0">
        {threadId && (
          <Button variant="ghost" size="sm" className="-ml-2 mb-2 md:hidden" onClick={() => selectThread(null)}>
            <ArrowLeft /> Chats
          </Button>
        )}
        <Conversation key={threadId ?? "new"} bot={bot} threadId={threadId} onCreated={selectThread} />
      </section>
    </div>
  );
}

function Conversation({
  bot,
  threadId,
  onCreated,
}: {
  bot: Bot;
  threadId: string | null;
  onCreated: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const thread = useThread(threadId);
  const createThread = useCreateThread(bot.id);
  const postMessage = usePostMessage(threadId ?? "");
  const activeRunId = thread.data?.active_run_id ?? null;
  const stream = useRunStream(activeRunId, () => {
    if (threadId) void queryClient.invalidateQueries({ queryKey: keys.thread(threadId) });
    void queryClient.invalidateQueries({ queryKey: keys.threads(bot.id) });
    void queryClient.invalidateQueries({ queryKey: keys.bot(bot.slug) });
  });
  const bottom = useRef<HTMLDivElement>(null);
  const messageCount = thread.data?.messages.length ?? 0;

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messageCount, stream.events.length]);

  async function send(content: string) {
    if (threadId) {
      await postMessage.mutateAsync(content);
    } else {
      const created = await createThread.mutateAsync(content);
      onCreated(created.id);
    }
  }

  const sendError = createThread.error ?? postMessage.error;

  return (
    <div className="flex min-h-[28rem] flex-col rounded-xl border">
      <div className="flex-1 space-y-6 p-4 sm:p-6">
        {!threadId && (
          <div className="py-12 text-center">
            <p className="font-medium">Chat with {bot.name}</p>
            <p className="text-sm text-muted-foreground">
              It remembers this conversation, and works on its own computer while it answers.
            </p>
          </div>
        )}
        {thread.isPending && threadId && <Skeleton className="h-24" />}
        {thread.isError && <ErrorNote error={thread.error} />}
        {thread.data?.messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        {activeRunId && <PendingReply runId={activeRunId} events={stream.events} />}
        <div ref={bottom} />
      </div>
      <Composer
        disabled={createThread.isPending || postMessage.isPending}
        busy={Boolean(activeRunId)}
        onSend={send}
      />
      {sendError && (
        <div className="px-4 pb-4">
          <ErrorNote error={sendError} />
        </div>
      )}
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-muted px-4 py-2.5 text-sm whitespace-pre-wrap">
          {message.content}
        </div>
      </div>
    );
  }
  const failed = message.run_status && message.run_status !== "completed";
  return (
    <div className="space-y-1">
      <div
        className={cn(
          "max-w-[95%] text-sm",
          failed && "rounded-lg bg-destructive/5 px-3 py-2 text-destructive",
        )}
      >
        <Markdown>{message.content}</Markdown>
      </div>
      {message.run_id && (
        <Link
          href={`/runs/${message.run_id}`}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          View run <ExternalLink className="size-3" />
        </Link>
      )}
    </div>
  );
}

function PendingReply({ runId, events }: { runId: string; events: RunEvent[] }) {
  const cancel = useCancelRun();
  return (
    <div className="space-y-3 rounded-xl bg-muted/40 p-4">
      <RunTimeline events={events} live />
      <div className="flex items-center gap-2">
        <Link href={`/runs/${runId}`} className={buttonVariants({ variant: "ghost", size: "xs" })}>
          Open run <ExternalLink />
        </Link>
        <Button
          variant="ghost"
          size="xs"
          disabled={cancel.isPending}
          onClick={() => cancel.mutate(runId)}
        >
          Stop
        </Button>
      </div>
    </div>
  );
}

function Composer({
  disabled,
  busy,
  onSend,
}: {
  disabled: boolean;
  busy: boolean;
  onSend: (content: string) => Promise<void>;
}) {
  const [text, setText] = useState("");

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const content = text.trim();
    if (!content || disabled) return;
    setText("");
    try {
      await onSend(content);
    } catch {
      setText(content); // keep what they typed; the error is shown below
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <form onSubmit={submit} className="border-t p-3">
      <div className="flex items-end gap-2">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          maxLength={20000}
          placeholder={busy ? "It will read this when it finishes the current reply…" : "Message…"}
          className="min-h-[2.75rem] resize-none border-0 shadow-none focus-visible:ring-0"
        />
        <Button type="submit" size="icon" aria-label="Send" disabled={disabled || !text.trim()}>
          <ArrowUp />
        </Button>
      </div>
    </form>
  );
}
