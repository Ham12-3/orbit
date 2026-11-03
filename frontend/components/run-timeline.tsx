"use client";

import { AlertTriangle, ChevronRight, Circle, Wrench } from "lucide-react";

import { Markdown } from "@/components/markdown";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { RunEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

type Item =
  | { kind: "event"; event: RunEvent }
  | { kind: "tool"; use: RunEvent; result: RunEvent | null };

/** Pair each tool call with its result, so the timeline reads call -> outcome. */
function toItems(events: RunEvent[]): Item[] {
  const results = new Map<string, RunEvent>();
  for (const event of events) {
    if (event.type === "tool_result" && typeof event.payload.tool_use_id === "string") {
      results.set(event.payload.tool_use_id, event);
    }
  }
  const paired = new Set<number>();
  const items: Item[] = [];
  for (const event of events) {
    if (event.type === "tool_use") {
      const result = results.get(String(event.payload.id)) ?? null;
      if (result) paired.add(result.id);
      items.push({ kind: "tool", use: event, result });
    } else if (!(event.type === "tool_result" && paired.has(event.id))) {
      items.push({ kind: "event", event });
    }
  }
  return items;
}

function str(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function toolSummary(payload: Record<string, unknown>): string {
  const input = (payload.input ?? {}) as Record<string, unknown>;
  const hint = input.description ?? input.command ?? input.file_path ?? input.url ?? input.pattern;
  return typeof hint === "string" ? hint : "";
}

function ToolItem({ use, result }: { use: RunEvent; result: RunEvent | null }) {
  const failed = result?.payload.is_error === true;
  return (
    <Collapsible className="group rounded-lg border bg-card">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm">
        <ChevronRight className="size-3.5 shrink-0 text-muted-foreground transition-transform group-data-[open]:rotate-90" />
        <Wrench className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="font-medium">{str(use.payload.name)}</span>
        <span className="truncate text-muted-foreground">{toolSummary(use.payload)}</span>
        <span className={cn("ml-auto shrink-0 text-xs", failed ? "text-destructive" : "text-muted-foreground")}>
          {result ? (failed ? "error" : "done") : "running…"}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-2 border-t px-3 py-2">
        <pre className="max-h-64 overflow-auto rounded-md bg-muted p-2 font-mono text-xs whitespace-pre-wrap">
          {str(use.payload.input)}
        </pre>
        {result && (
          <pre
            className={cn(
              "max-h-80 overflow-auto rounded-md p-2 font-mono text-xs whitespace-pre-wrap",
              failed ? "bg-destructive/10 text-destructive" : "bg-muted",
            )}
          >
            {str(result.payload.content) || "(no output)"}
          </pre>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

function EventItem({ event }: { event: RunEvent }) {
  switch (event.type) {
    case "text":
      return <Markdown className="text-sm">{str(event.payload.text)}</Markdown>;
    case "thinking":
      return (
        <p className="border-l-2 pl-3 text-sm text-muted-foreground italic">{str(event.payload.thinking)}</p>
      );
    case "error":
      return (
        <div className="flex gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span className="whitespace-pre-wrap">{str(event.payload.message)}</span>
        </div>
      );
    case "tool_result":
      return (
        <pre className="max-h-64 overflow-auto rounded-md bg-muted p-2 font-mono text-xs whitespace-pre-wrap">
          {str(event.payload.content)}
        </pre>
      );
    default:
      return (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Circle className="size-1.5 fill-current" />
          {str(event.payload.message ?? event.type)}
        </p>
      );
  }
}

export function RunTimeline({ events, live }: { events: RunEvent[]; live?: boolean }) {
  const items = toItems(events);
  return (
    <div className="space-y-3">
      {items.map((item) =>
        item.kind === "tool" ? (
          <ToolItem key={item.use.id} use={item.use} result={item.result} />
        ) : (
          <EventItem key={item.event.id} event={item.event} />
        ),
      )}
      {live && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="size-1.5 animate-pulse rounded-full bg-sky-500" /> Working…
        </p>
      )}
    </div>
  );
}
