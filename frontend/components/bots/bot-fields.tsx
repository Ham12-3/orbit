"use client";

import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { MODELS } from "@/lib/types";
import { cn } from "@/lib/utils";

const EMOJIS = ["🤖", "🔎", "✍️", "📬", "📅", "📈", "🧹", "🛠️"];

export function EmojiPicker({ value, onChange }: { value: string; onChange: (emoji: string) => void }) {
  const options = EMOJIS.includes(value) ? EMOJIS : [value, ...EMOJIS];
  return (
    <div className="space-y-2">
      <Label>Avatar</Label>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(option)}
            aria-pressed={value === option}
            className={cn(
              "flex size-10 items-center justify-center rounded-lg border text-xl transition-colors",
              value === option ? "border-foreground bg-muted" : "hover:bg-muted",
            )}
          >
            {option}
          </button>
        ))}
      </div>
    </div>
  );
}

export function ModelSelect({ value, onChange }: { value: string; onChange: (model: string) => void }) {
  return (
    <div className="space-y-2">
      <Label>Model</Label>
      <Select value={value} onValueChange={(next) => next && onChange(next)} items={MODELS}>
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(MODELS).map(([model, label]) => (
            <SelectItem key={model} value={model}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
