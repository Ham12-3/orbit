"use client";

import { useEffect, useRef, useState } from "react";

import { backendUrl } from "@/lib/api";
import type { Run, RunEvent } from "@/lib/types";

export interface RunStream {
  events: RunEvent[];
  run: Run | null;
  ended: boolean;
  error: string | null;
}

const EMPTY: RunStream = { events: [], run: null, ended: false, error: null };
const MAX_BACKOFF_MS = 15_000;

/**
 * Follows a run live over SSE (through the Next.js forwarder). The browser reconnects by
 * itself on network blips, sending Last-Event-ID; if the stream is closed for good this
 * reopens it with `after=<last event id>` so nothing is missed or repeated.
 */
export function useRunStream(runId: string | null, onEnd?: (run: Run | null) => void): RunStream {
  // Tagged with its run, so switching runs shows an empty stream without resetting state.
  const [tagged, setTagged] = useState<{ runId: string | null; stream: RunStream }>({
    runId: null,
    stream: EMPTY,
  });
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
    const setState = (update: (s: RunStream) => RunStream) =>
      setTagged((current) => ({
        runId,
        stream: update(current.runId === runId ? current.stream : EMPTY),
      }));

    const open = () => {
      if (stopped) return;
      const query = lastId ? `?after=${lastId}` : "";
      source = new EventSource(backendUrl(`/api/runs/${runId}/stream${query}`));

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
          attempts += 1;
          setState((s) => ({ ...s, error: "connection lost" }));
          retryTimer = setTimeout(open, Math.min(1000 * 2 ** attempts, MAX_BACKOFF_MS));
        }
      };
    };

    open();
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      source?.close();
    };
  }, [runId]);

  return tagged.runId === runId ? tagged.stream : EMPTY;
}
