"use client";

import { ChevronRight } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { EmojiPicker, ModelSelect } from "@/components/bots/bot-fields";
import { ErrorNote } from "@/components/error-note";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useClaudeMd, useUpdateBot } from "@/lib/queries";
import type { Bot, BotUpdate } from "@/lib/types";

export function SettingsPanel({ bot }: { bot: Bot }) {
  return (
    <div className="max-w-2xl space-y-8">
      {/* Start over from the saved values whenever they change (not on status updates). */}
      <BotForm key={configKey(bot)} bot={bot} />
      <ClaudeMdPreview bot={bot} />
      <p className="rounded-lg bg-muted/60 px-4 py-3 text-sm text-muted-foreground">
        Tool policies, app connections and deleting a bot arrive in Phase 4.
      </p>
    </div>
  );
}

function configKey(bot: Bot): string {
  return JSON.stringify([
    bot.avatar_emoji,
    bot.name,
    bot.job_description,
    bot.instructions,
    bot.model,
    bot.daily_token_budget,
    bot.max_turns_per_run,
  ]);
}

function BotForm({ bot }: { bot: Bot }) {
  const update = useUpdateBot(bot);
  const [emoji, setEmoji] = useState(bot.avatar_emoji);
  const [name, setName] = useState(bot.name);
  const [job, setJob] = useState(bot.job_description);
  const [instructions, setInstructions] = useState(bot.instructions);
  const [model, setModel] = useState(bot.model);
  const [budget, setBudget] = useState(String(bot.daily_token_budget));
  const [maxTurns, setMaxTurns] = useState(String(bot.max_turns_per_run));

  const changes: BotUpdate = {};
  if (emoji !== bot.avatar_emoji) changes.avatar_emoji = emoji;
  if (name.trim() !== bot.name) changes.name = name.trim();
  if (job.trim() !== bot.job_description) changes.job_description = job.trim();
  if (instructions !== bot.instructions) changes.instructions = instructions;
  if (model !== bot.model) changes.model = model;
  if (Number(budget) !== bot.daily_token_budget) changes.daily_token_budget = Number(budget);
  if (Number(maxTurns) !== bot.max_turns_per_run) changes.max_turns_per_run = Number(maxTurns);
  const dirty = Object.keys(changes).length > 0;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    await update.mutateAsync(changes);
    toast.success("Saved. The bot uses the new settings from its next run.");
  }

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      <EmojiPicker value={emoji} onChange={setEmoji} />
      <div className="space-y-2">
        <Label htmlFor="edit-name">Name</Label>
        <Input id="edit-name" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="edit-job">Job</Label>
        <Textarea id="edit-job" required maxLength={4000} rows={3} value={job} onChange={(e) => setJob(e.target.value)} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="edit-instructions">Instructions</Label>
        <Textarea
          id="edit-instructions"
          maxLength={20000}
          rows={6}
          placeholder="How you like things done: tone, format, what to avoid…"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
        />
      </div>
      <ModelSelect value={model} onChange={setModel} />
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="edit-budget">Daily token budget</Label>
          <Input id="edit-budget" type="number" min={1000} step={1000} required value={budget} onChange={(e) => setBudget(e.target.value)} />
          <p className="text-xs text-muted-foreground">Input + output + cache writes, reset at 00:00 UTC.</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="edit-turns">Max turns per run</Label>
          <Input id="edit-turns" type="number" min={1} max={500} required value={maxTurns} onChange={(e) => setMaxTurns(e.target.value)} />
        </div>
      </div>
      {update.isError && <ErrorNote error={update.error} />}
      <div className="flex items-center justify-end gap-3">
        <p className="text-xs text-muted-foreground">Changes apply from the bot&apos;s next run.</p>
        <Button type="submit" disabled={!dirty || update.isPending}>
          {update.isPending ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}

function ClaudeMdPreview({ bot }: { bot: Bot }) {
  const [open, setOpen] = useState(false);
  const claudeMd = useClaudeMd(bot.id);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="group rounded-xl border">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm">
        <ChevronRight className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[open]:rotate-90" />
        <span className="font-medium">What {bot.name} reads before every task</span>
        <span className="font-mono text-xs text-muted-foreground">CLAUDE.md</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t px-4 py-3">
        <p className="mb-3 text-xs text-muted-foreground">
          Built from these settings and its memory, and written to its computer at the start of
          each run.
        </p>
        {claudeMd.isPending && <Skeleton className="h-40" />}
        {claudeMd.isError && <ErrorNote error={claudeMd.error} />}
        {claudeMd.data && (
          <pre className="max-h-[32rem] overflow-auto rounded-md bg-muted p-3 font-mono text-xs whitespace-pre-wrap">
            {claudeMd.data.content}
          </pre>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}
