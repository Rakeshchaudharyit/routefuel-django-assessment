"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { getHealth } from "@/lib/api/client";
export function useHealth() {
  const [status, setStatus] = useState<
    "checking" | "connected" | "disconnected"
  >("checking");
  const active = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setStatus("checking");
    try {
      await getHealth(controller.signal);
      if (!controller.signal.aborted) setStatus("connected");
    } catch {
      if (!controller.signal.aborted) setStatus("disconnected");
    }
  }, []);
  useEffect(() => {
    const initial = setTimeout(() => void refresh(), 0);
    const interval = setInterval(() => void refresh(), 60_000);
    return () => {
      clearTimeout(initial);
      clearInterval(interval);
      active.current?.abort();
    };
  }, [refresh]);
  return { status, refresh };
}
