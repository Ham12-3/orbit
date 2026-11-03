"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import {
  TERMINAL_STATUSES,
  type Bot,
  type BotCreate,
  type Run,
  type RunEvent,
  type Thread,
  type ThreadDetail,
} from "@/lib/types";

export const keys = {
  bots: ["bots"] as const,
  bot: (slug: string) => ["bot", slug] as const,
  botById: (id: string) => ["bot-id", id] as const,
  botRuns: (botId: string) => ["bot-runs", botId] as const,
  threads: (botId: string) => ["threads", botId] as const,
  thread: (threadId: string) => ["thread", threadId] as const,
  run: (runId: string) => ["run", runId] as const,
};

export function useBots() {
  return useQuery({ queryKey: keys.bots, queryFn: () => api<Bot[]>("/api/bots") });
}

export function useBot(slug: string) {
  return useQuery({
    queryKey: keys.bot(slug),
    queryFn: () => api<Bot>(`/api/bots/by-slug/${encodeURIComponent(slug)}`),
    // The bot is released just after its run ends; keep the status badge honest.
    refetchInterval: (query) => (query.state.data?.status === "running" ? 3000 : false),
  });
}

export function useBotById(botId: string | undefined) {
  return useQuery({
    queryKey: keys.botById(botId ?? ""),
    queryFn: () => api<Bot>(`/api/bots/${botId}`),
    enabled: Boolean(botId),
  });
}

export function useBotRuns(botId: string | undefined) {
  return useQuery({
    queryKey: keys.botRuns(botId ?? ""),
    queryFn: () => api<Run[]>(`/api/bots/${botId}/runs`),
    enabled: Boolean(botId),
    // While anything is still going, keep the list fresh.
    refetchInterval: (query) =>
      query.state.data?.some((run) => !TERMINAL_STATUSES.has(run.status)) ? 3000 : false,
  });
}

export function useThreads(botId: string | undefined) {
  return useQuery({
    queryKey: keys.threads(botId ?? ""),
    queryFn: () => api<Thread[]>(`/api/bots/${botId}/threads`),
    enabled: Boolean(botId),
  });
}

export function useThread(threadId: string | null) {
  return useQuery({
    queryKey: keys.thread(threadId ?? ""),
    queryFn: () => api<ThreadDetail>(`/api/threads/${threadId}`),
    enabled: Boolean(threadId),
    // Safety net: if the run behind the last message has finished but its reply is not
    // here yet, look again shortly.
    refetchInterval: (query) => {
      const last = query.state.data?.messages.at(-1);
      return last?.role === "user" && last.run_status && TERMINAL_STATUSES.has(last.run_status)
        ? 1500
        : false;
    },
  });
}

export function useRun(runId: string) {
  return useQuery({
    queryKey: keys.run(runId),
    queryFn: () => api<Run & { events: RunEvent[] }>(`/api/runs/${runId}`),
  });
}

export function useCreateBot() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: BotCreate) => api<Bot>("/api/bots", { method: "POST", body }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.bots });
    },
  });
}

export function useStartRun(botId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (prompt: string) =>
      api<Run>(`/api/bots/${botId}/runs`, { method: "POST", body: { prompt } }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.botRuns(botId) });
    },
  });
}

export function useCreateThread(botId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (message: string) =>
      api<ThreadDetail>(`/api/bots/${botId}/threads`, { method: "POST", body: { message } }),
    onSuccess: async (thread) => {
      queryClient.setQueryData(keys.thread(thread.id), thread);
      await queryClient.invalidateQueries({ queryKey: keys.threads(botId) });
    },
  });
}

export function usePostMessage(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (content: string) =>
      api<ThreadDetail>(`/api/threads/${threadId}/messages`, { method: "POST", body: { content } }),
    onSuccess: (thread) => {
      queryClient.setQueryData(keys.thread(thread.id), thread);
    },
  });
}

export function useCancelRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api<Run>(`/api/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: async (run) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.run(run.id) }),
        queryClient.invalidateQueries({ queryKey: keys.botRuns(run.bot_id) }),
        run.thread_id
          ? queryClient.invalidateQueries({ queryKey: keys.thread(run.thread_id) })
          : Promise.resolve(),
      ]);
    },
  });
}
