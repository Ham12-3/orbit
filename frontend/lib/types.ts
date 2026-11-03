// Mirrors backend/app/schemas. Keep in sync when the API changes.

export type RunStatus =
  | "queued"
  | "starting"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "timed_out";

export type BotStatus = "idle" | "running" | "paused" | "error";

export type RunTrigger =
  | "manual"
  | "chat"
  | "schedule"
  | "event"
  | "handoff"
  | "approval_followup";

export type RunEventType = "text" | "tool_use" | "tool_result" | "thinking" | "status" | "error";

export const TERMINAL_STATUSES: ReadonlySet<RunStatus> = new Set([
  "completed",
  "failed",
  "cancelled",
  "timed_out",
]);

export interface Me {
  id: string;
  email: string | null;
}

export interface Bot {
  id: string;
  name: string;
  slug: string;
  avatar_emoji: string;
  job_description: string;
  instructions: string;
  model: string;
  status: BotStatus;
  enabled: boolean;
  daily_token_budget: number;
  max_turns_per_run: number;
  sandbox_id: string | null;
  active_run_id: string | null;
  created_at: string;
  updated_at: string;
  last_run_status: RunStatus | null;
  last_run_at: string | null;
  cost_today_usd: number;
}

export interface BotCreate {
  name: string;
  avatar_emoji: string;
  job_description: string;
  instructions: string;
  model: string;
  max_turns_per_run: number;
  daily_token_budget: number;
}

export interface Run {
  id: string;
  bot_id: string;
  thread_id: string | null;
  trigger_type: RunTrigger;
  status: RunStatus;
  input_prompt: string;
  final_summary: string | null;
  error: string | null;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: number;
  num_turns: number | null;
  agent_session_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunEvent {
  id: number;
  seq: number | null;
  type: RunEventType;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface StreamTicket {
  ticket: string;
  expires_at: string;
}

export interface Thread {
  id: string;
  bot_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  role: "user" | "bot";
  content: string;
  run_id: string | null;
  run_status: RunStatus | null;
  created_at: string;
}

export interface ThreadDetail extends Thread {
  messages: Message[];
  active_run_id: string | null;
}

export const MODELS: Record<string, string> = {
  "claude-sonnet-5-5": "Claude Sonnet 5.5 · balanced (default)",
  "claude-haiku-5-5": "Claude Haiku 5.5 · fast and cheap",
  "claude-opus-5-5": "Claude Opus 5.5 · most capable",
};
