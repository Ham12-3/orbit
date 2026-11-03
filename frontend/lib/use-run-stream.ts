"use client";

import { useEffect, useRef, useState } from "react";

import { api, API_URL } from "@/lib/api";
import type { Run, RunEvent, StreamTicket } from "@/lib/types";

export interface RunStream {
  events: RunEvent[];
  run: Run | null;
  ended: boolean;
  error: string | null;
}

const EMPTY: RunStream = { events: [], run: null, ended: false, error: null };
const MAX_BACKOFF_MS = 15_000;

/**
 * Follows a run live over SSE. EventSource cannot send an Authorization header, so it first
 * gets a short-lived stream ticket. The browser reconnects by itself on network blips (sending
 * Last-Event-ID); when the stream is closed for good (e.g. the ticket expired) this fetches a
 * new ticket and resumes with `after=<last event id>`.
 */
export function useRunStream(runId: string | null, onEnd?: (run: Run | null) => void): RunStream {
  const [state, setState] = useState<RunStream>(EMPTY);
  const onEndRef = useRef(onEnd);

  useEffect(() => {
    onEndRef.current = onEnd;
  }, [onEnd]);

  useEffect(() => {
    if (!runId) return;
    let source: EventSource | null = null;
    let lastId = 0;
    let attempts = 0;
    let stopped = false;
    let latestRun: Run | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    setState(EMPTY);

    const open = async () => {
      let ticket: StreamTicket;
      try {
        ticket = await api<StreamTicket>(`/api/runs/${runId}/stream-ticket`, { method: "POST" });
      } catch (err) {
        if (!stopped) {
          setState((s) => ({ ...s, error: err instanceof Error ? err.message : "Stream failed" }));
          schedule();
        }
        return;
      }
      if (stopped) return;

      const url = new URL(`${API_URL}/api/runs/${runId}/stream`);
      url.searchParams.set("ticket", ticket.ticket);
      if (lastId) url.searchParams.set("after", String(lastId));
      source = new EventSource(url);

      source.addEventListener("run_event", (e) => {
        const event = JSON.parse((e as MessageEvent<string>).data) as RunEvent;
        lastId = Math.max(lastId, event.id);
        attempts = 0;
        setState((s) =>
          s.events.some((x) => x.id === event.id)
            ? s
            : { ...s, error: null, events: [...s.events, event] },
        );
      });
      source.addEventListener("run", (e) => {
        latestRun = JSON.parse((e as MessageEvent<string>).data) as Run;
        setState((s) => ({ ...s, error: null, run: latestRun }));
      });
      source.addEventListener("end", () => {
        stopped = true;
        source?.close();
        setState((s) => ({ ...s, ended: true }));
        onEndRef.current?.(latestRun);
      });
      source.onerror = () => {
        // CONNECTING means the browser is retrying by itself; CLOSED means it gave up.
        if (source?.readyState === EventSource.CLOSED && !stopped) {
          schedule();
        }
      };
    };

    const schedule = () => {
      attempts += 1;
      retryTimer = setTimeout(open, Math.min(1000 * 2 ** attempts, MAX_BACKOFF_MS));
    };

    void open();
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      source?.close();
    };
  }, [runId]);

  return state;
}
