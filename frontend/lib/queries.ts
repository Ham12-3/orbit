"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, apiBytes, encodePath } from "@/lib/api";
import {
  TERMINAL_STATUSES,
  type Bot,
  type BotCreate,
  type BotUpdate,
  type MemoryFile,
  type MemoryFileDetail,
  type Run,
  type RunEvent,
  type Thread,
  type ThreadDetail,
  type WorkspaceListing,
} from "@/lib/types";

export const keys = {
  bots: ["bots"] as const,
  bot: (slug: string) => ["bot", slug] as const,
  botById: (id: string) => ["bot-id", id] as const,
  botRuns: (botId: string) => ["bot-runs", botId] as const,
  threads: (botId: string) => ["threads", botId] as const,
  thread: (threadId: string) => ["thread", threadId] as const,
  run: (runId: string) => ["run", runId] as const,
  memory: (botId: string) => ["memory", botId] as const,
  memoryFile: (botId: string, path: string) => ["memory", botId, path] as const,
  claudeMd: (botId: string) => ["claude-md", botId] as const,
  files: (botId: string) => ["files", botId] as const,
  fileContent: (botId: string, path: string, version: string) =>
    ["file-content", botId, path, version] as const,
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

export function useUpdateBot(bot: Bot) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: BotUpdate) => api<Bot>(`/api/bots/${bot.id}`, { method: "PATCH", body }),
    onSuccess: async (updated) => {
      queryClient.setQueryData(keys.bot(updated.slug), updated);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.bots }),
        queryClient.invalidateQueries({ queryKey: keys.claudeMd(updated.id) }),
      ]);
    },
  });
}

export function useClaudeMd(botId: string) {
  return useQuery({
    queryKey: keys.claudeMd(botId),
    queryFn: () => api<{ content: string }>(`/api/bots/${botId}/claude-md`),
  });
}

// ---- Memory ------------------------------------------------------------------------

function memoryUrl(botId: string, path: string) {
  return `/api/bots/${botId}/memory/${encodePath(path)}`;
}

export function useMemory(botId: string) {
  return useQuery({
    queryKey: keys.memory(botId),
    queryFn: () => api<MemoryFile[]>(`/api/bots/${botId}/memory`),
  });
}

export function useMemoryFile(botId: string, path: string | null) {
  return useQuery({
    queryKey: keys.memoryFile(botId, path ?? ""),
    queryFn: () => api<MemoryFileDetail>(memoryUrl(botId, path ?? "")),
    enabled: Boolean(path),
  });
}

export function useSaveMemory(botId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ path, content }: { path: string; content: string }) =>
      api<MemoryFileDetail>(memoryUrl(botId, path), { method: "PUT", body: { content } }),
    onSuccess: async (file) => {
      queryClient.setQueryData(keys.memoryFile(botId, file.path), file);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.memory(botId), exact: true }),
        queryClient.invalidateQueries({ queryKey: keys.claudeMd(botId) }),
      ]);
    },
  });
}

export function useDeleteMemory(botId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (path: string) => api<void>(memoryUrl(botId, path), { method: "DELETE" }),
    onSuccess: async (_, path) => {
      queryClient.removeQueries({ queryKey: keys.memoryFile(botId, path) });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.memory(botId), exact: true }),
        queryClient.invalidateQueries({ queryKey: keys.claudeMd(botId) }),
      ]);
    },
  });
}

// ---- Workspace files ---------------------------------------------------------------

export function fileUrl(botId: string, path: string) {
  return `/api/bots/${botId}/files/content/${encodePath(path)}`;
}

export function useWorkspace(botId: string) {
  return useQuery({
    queryKey: keys.files(botId),
    queryFn: () => api<WorkspaceListing>(`/api/bots/${botId}/files`),
  });
}

export function useRefreshWorkspace(botId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api<WorkspaceListing>(`/api/bots/${botId}/files?live=true`, { slow: true }),
    onSuccess: (listing) => {
      queryClient.setQueryData(keys.files(botId), listing);
    },
  });
}

/** `version` (the file's modified time) makes a changed file load again. */
export function useFileContent(botId: string, path: string | null, version: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.fileContent(botId, path ?? "", version),
    queryFn: () => apiBytes(fileUrl(botId, path ?? "")),
    enabled: Boolean(path) && enabled,
    staleTime: Infinity,
    retry: false,
  });
}
