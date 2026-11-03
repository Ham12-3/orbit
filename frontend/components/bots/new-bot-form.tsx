"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { EmojiPicker, ModelSelect } from "@/components/bots/bot-fields";
import { ErrorNote } from "@/components/error-note";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useCreateBot } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function NewBotForm() {
  const router = useRouter();
  const createBot = useCreateBot();
  const [emoji, setEmoji] = useState("🤖");
  const [name, setName] = useState("");
  const [job, setJob] = useState("");
  const [instructions, setInstructions] = useState("");
  const [model, setModel] = useState("claude-sonnet-5-5");
  const [budget, setBudget] = useState("2000000");
  const [maxTurns, setMaxTurns] = useState("50");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const bot = await createBot.mutateAsync({
      name: name.trim(),
      avatar_emoji: emoji,
      job_description: job.trim(),
      instructions,
      model,
      daily_token_budget: Number(budget),
      max_turns_per_run: Number(maxTurns),
    });
    toast.success(`${bot.name} is ready`);
    router.push(`/bots/${bot.slug}`);
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Link href="/bots" className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2")}>
        <ArrowLeft /> Bots
      </Link>
      <div>
        <h1 className="font-heading text-2xl font-semibold tracking-tight">New bot</h1>
        <p className="text-sm text-muted-foreground">
          Its own cloud computer is created on its first run.
        </p>
      </div>

      <form onSubmit={onSubmit} className="space-y-6">
        <EmojiPicker value={emoji} onChange={setEmoji} />

        <div className="space-y-2">
          <Label htmlFor="name">Name</Label>
          <Input id="name" required maxLength={80} placeholder="Researcher" value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <div className="space-y-2">
          <Label htmlFor="job">Job</Label>
          <Textarea
            id="job"
            required
            maxLength={4000}
            rows={3}
            placeholder="Find and summarise news about solar energy each morning."
            value={job}
            onChange={(e) => setJob(e.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="instructions">Instructions</Label>
          <Textarea
            id="instructions"
            maxLength={20000}
            rows={5}
            placeholder="How you like things done: tone, format, what to avoid…"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">Optional. The bot reads this before every task.</p>
        </div>

        <ModelSelect value={model} onChange={setModel} />

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="budget">Daily token budget</Label>
            <Input id="budget" type="number" min={1000} step={1000} required value={budget} onChange={(e) => setBudget(e.target.value)} />
            <p className="text-xs text-muted-foreground">Input + output + cache writes, reset at 00:00 UTC.</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="turns">Max turns per run</Label>
            <Input id="turns" type="number" min={1} max={500} required value={maxTurns} onChange={(e) => setMaxTurns(e.target.value)} />
          </div>
        </div>

        <p className="rounded-lg bg-muted/60 px-4 py-3 text-sm text-muted-foreground">
          Connecting apps (Gmail, Calendar, Slack, GitHub) arrives in Phase 4.
        </p>

        {createBot.isError && <ErrorNote error={createBot.error} />}

        <div className="flex justify-end gap-2">
          <Link href="/bots" className={buttonVariants({ variant: "ghost" })}>
            Cancel
          </Link>
          <Button type="submit" disabled={createBot.isPending}>
            {createBot.isPending ? "Creating…" : "Create bot"}
          </Button>
        </div>
      </form>
    </div>
  );
}
