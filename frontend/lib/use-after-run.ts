"use client";

import { useEffect, useRef } from "react";

import type { Bot } from "@/lib/types";

/** Call `onRunEnded` when the bot goes from running to anything else. */
export function useAfterRun(bot: Bot, onRunEnded: () => void) {
  const wasRunning = useRef(bot.status === "running");
  const callback = useRef(onRunEnded);

  useEffect(() => {
    callback.current = onRunEnded;
  });

  useEffect(() => {
    const running = bot.status === "running";
    if (wasRunning.current && !running) callback.current();
    wasRunning.current = running;
  }, [bot.status]);
}
