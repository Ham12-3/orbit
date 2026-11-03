"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Brain, FilePlus, Pencil, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { ErrorNote } from "@/components/error-note";
import { Markdown } from "@/components/markdown";
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
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { timeAgo } from "@/lib/format";
import { useDeleteMemory, useMemory, useMemoryFile, useSaveMemory } from "@/lib/queries";
import type { Bot, MemoryFile } from "@/lib/types";
import { useAfterRun } from "@/lib/use-after-run";
import { cn } from "@/lib/utils";

const NEW = Symbol("new file");
type Selection = string | typeof NEW | null;

export function MemoryPanel({ bot }: { bot: Bot }) {
  const queryClient = useQueryClient();
  const memory = useMemory(bot.id);
  const [selected, setSelected] = useState<Selection>(null);

  // A run that just ended may have saved new memory.
  useAfterRun(bot, () => void queryClient.invalidateQueries({ queryKey: ["memory", bot.id] }));

  const files = memory.data ?? [];
  const current = typeof selected === "string" ? files.find((f) => f.path === selected) : undefined;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        What {bot.name} has learned. It reads these notes at the start of every task. Your edits
        and deletes reach its computer when its next run starts.
      </p>
      <div className="grid gap-6 md:grid-cols-[240px_1fr]">
        <aside className={cn("space-y-2", selected !== null && "hidden md:block")}>
          <Button variant="outline" className="w-full justify-start" onClick={() => setSelected(NEW)}>
            <FilePlus /> New note
          </Button>
          {memory.isPending && <Skeleton className="h-24" />}
          {memory.isError && <ErrorNote error={memory.error} />}
          <nav className="space-y-0.5">
            {files.map((file) => (
              <FileRow
                key={file.path}
                file={file}
                active={file.path === selected}
                onClick={() => setSelected(file.path)}
              />
            ))}
          </nav>
        </aside>
        <section className="min-w-0">
          {selected !== null && (
            <Button variant="ghost" size="sm" className="-ml-2 mb-2 md:hidden" onClick={() => setSelected(null)}>
              <ArrowLeft /> Notes
            </Button>
          )}
          {selected === NEW ? (
            <NewNote
              bot={bot}
              taken={new Set(files.map((f) => f.path))}
              onSaved={setSelected}
              onCancel={() => setSelected(null)}
            />
          ) : current ? (
            <NoteView key={current.path} bot={bot} file={current} onDeleted={() => setSelected(null)} />
          ) : (
            <EmptyState bot={bot} hasFiles={files.length > 0} />
          )}
        </section>
      </div>
    </div>
  );
}

function FileRow({ file, active, onClick }: { file: MemoryFile; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted",
        active && "bg-muted",
      )}
    >
      <span className="block truncate font-mono text-sm">{file.path}</span>
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {file.updated_by === "user" ? "You" : "Bot"} · {timeAgo(file.updated_at)}
        {file.sync_state === "push" && <span className="size-1.5 rounded-full bg-amber-500" aria-label="Not on the bot's computer yet" />}
      </span>
    </button>
  );
}

function EmptyState({ bot, hasFiles }: { bot: Bot; hasFiles: boolean }) {
  return (
    <div className={cn("rounded-xl border border-dashed px-6 py-12 text-center", hasFiles && "hidden md:block")}>
      <Brain className="mx-auto mb-3 size-6 text-muted-foreground" />
      {hasFiles ? (
        <p className="text-sm text-muted-foreground">Pick a note to read or edit it.</p>
      ) : (
        <>
          <p className="font-medium">{bot.name} hasn&apos;t saved anything yet</p>
          <p className="mx-auto max-w-sm text-sm text-muted-foreground">
            Tell it something in Chat, like &ldquo;I prefer short bullet summaries&rdquo;. It saves
            what it learns here when the run ends. You can also write a note yourself.
          </p>
        </>
      )}
    </div>
  );
}

function NoteView({ bot, file, onDeleted }: { bot: Bot; file: MemoryFile; onDeleted: () => void }) {
  const detail = useMemoryFile(bot.id, file.path);
  const save = useSaveMemory(bot.id);
  const remove = useDeleteMemory(bot.id);
  const [draft, setDraft] = useState<string | null>(null);

  async function onSave(event: FormEvent) {
    event.preventDefault();
    if (draft === null) return;
    await save.mutateAsync({ path: file.path, content: draft });
    setDraft(null);
    toast.success(`Saved. ${bot.name} sees it from its next run.`);
  }

  async function onDelete() {
    await remove.mutateAsync(file.path);
    toast.success(`Deleted ${file.path}`);
    onDeleted();
  }

  return (
    <div className="space-y-3 rounded-xl border p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <h3 className="truncate font-mono text-sm font-medium">memory/{file.path}</h3>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>
              {file.updated_by === "user" ? "Edited by you" : `Written by ${bot.name}`} {timeAgo(file.updated_at)}
            </span>
            {file.sync_state === "push" && (
              <Badge variant="secondary" className="bg-amber-500/10 text-amber-700 dark:text-amber-300">
                Reaches the bot on its next run
              </Badge>
            )}
          </div>
        </div>
        {draft === null && (
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={!detail.data} onClick={() => setDraft(detail.data?.content ?? "")}>
              <Pencil /> Edit
            </Button>
            <AlertDialog>
              <AlertDialogTrigger
                className={buttonVariants({ variant: "outline", size: "sm" })}
                disabled={remove.isPending}
              >
                <Trash2 /> Delete
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete this note?</AlertDialogTitle>
                  <AlertDialogDescription>
                    {bot.name} forgets memory/{file.path}. It is removed from its computer when its
                    next run starts.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Keep it</AlertDialogCancel>
                  <AlertDialogAction onClick={onDelete}>Delete</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        )}
      </div>

      {detail.isPending && <Skeleton className="h-32" />}
      {detail.isError && <ErrorNote error={detail.error} />}
      {remove.isError && <ErrorNote error={remove.error} />}
      {draft !== null ? (
        <form onSubmit={onSave} className="space-y-3">
          <Textarea
            aria-label={`Contents of ${file.path}`}
            className="min-h-64 font-mono text-sm"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          {save.isError && <ErrorNote error={save.error} />}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setDraft(null)}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending || draft === detail.data?.content}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </form>
      ) : (
        detail.data &&
        (detail.data.content.trim() ? (
          <Markdown className="text-sm">{detail.data.content}</Markdown>
        ) : (
          <p className="text-sm text-muted-foreground">(empty)</p>
        ))
      )}
    </div>
  );
}

function NewNote({
  bot,
  taken,
  onSaved,
  onCancel,
}: {
  bot: Bot;
  taken: ReadonlySet<string>;
  onSaved: (path: string) => void;
  onCancel: () => void;
}) {
  const save = useSaveMemory(bot.id);
  const [path, setPath] = useState("notes.md");
  const [content, setContent] = useState("");
  const exists = taken.has(path.trim());

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const file = await save.mutateAsync({ path: path.trim(), content });
    toast.success(`Saved. ${bot.name} sees it from its next run.`);
    onSaved(file.path);
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4 rounded-xl border p-4 sm:p-6">
      <div className="space-y-2">
        <Label htmlFor="memory-path">File name</Label>
        <div className="flex items-center gap-1 font-mono text-sm">
          <span className="text-muted-foreground">memory/</span>
          <Input id="memory-path" required maxLength={200} className="font-mono" value={path} onChange={(e) => setPath(e.target.value)} />
        </div>
        {exists ? (
          <p className="text-xs text-destructive">A note with this name exists. Open it to edit it.</p>
        ) : (
          <p className="text-xs text-muted-foreground">
            One topic per Markdown file, e.g. preferences.md or people/alex.md.
          </p>
        )}
      </div>
      <div className="space-y-2">
        <Label htmlFor="memory-content">Note</Label>
        <Textarea
          id="memory-content"
          className="min-h-48 font-mono text-sm"
          placeholder="- I prefer short bullet summaries"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
      </div>
      {save.isError && <ErrorNote error={save.error} />}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={save.isPending || !path.trim() || exists}>
          {save.isPending ? "Saving…" : "Save note"}
        </Button>
      </div>
    </form>
  );
}
