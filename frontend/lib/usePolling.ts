"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type PollingOptions<T> = {
  enabled: boolean;
  intervalMs: number;
  fetcher: (signal: AbortSignal) => Promise<T>;
};

export function usePolling<T>({ enabled, intervalMs, fetcher }: PollingOptions<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [loading, setLoading] = useState(false);
  const [consecutiveErrors, setConsecutiveErrors] = useState(0);
  const [stopped, setStopped] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const dataRef = useRef<T | null>(null);
  const inFlight = useRef<AbortController | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => { dataRef.current = data; }, [data]);

  useEffect(() => {
    if (!enabled) {
      controllerRef.current?.abort();
      controllerRef.current = null;
      inFlight.current = null;
      setLoading(false);
      return;
    }

    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    let halted = false;

    const schedule = (delay: number) => {
      if (disposed || halted || document.visibilityState === "hidden") return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => void run(), delay);
    };

    const run = async () => {
      if (disposed || halted || document.visibilityState === "hidden" || inFlight.current) return;
      const controller = new AbortController();
      inFlight.current = controller;
      controllerRef.current = controller;
      setLoading(!dataRef.current);
      try {
        const value = await fetcher(controller.signal);
        if (disposed || controller.signal.aborted) return;
        failures = 0;
        dataRef.current = value;
        setData(value);
        setError(null);
        setStale(false);
        setConsecutiveErrors(0);
        schedule(intervalMs);
      } catch (cause) {
        if (disposed || controller.signal.aborted) return;
        failures += 1;
        const status = typeof cause === "object" && cause !== null && "status" in cause
          ? Number((cause as { status: unknown }).status) : 0;
        const message = cause instanceof Error ? cause.message : "Monitoring gagal diperbarui.";
        setError(message);
        setStale(Boolean(dataRef.current));
        setConsecutiveErrors(failures);
        if ([401, 403, 404, 422].includes(status) || failures >= 5) {
          halted = true;
          setStopped(true);
        } else {
          schedule(Math.min(intervalMs * (2 ** failures), 300_000));
        }
      } finally {
        if (controllerRef.current === controller) controllerRef.current = null;
        if (inFlight.current === controller) inFlight.current = null;
        if (!disposed) setLoading(false);
      }
    };

    const onVisibility = () => {
      if (document.visibilityState === "visible" && !inFlight.current && !halted) void run();
      if (document.visibilityState === "hidden" && timer) clearTimeout(timer);
    };

    setStopped(false);
    void run();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      const activeController = controllerRef.current;
      activeController?.abort();
      if (inFlight.current === activeController) inFlight.current = null;
      controllerRef.current = null;
    };
  }, [enabled, intervalMs, fetcher, retryKey]);

  const retry = useCallback(() => {
    setError(null);
    setStale(false);
    setConsecutiveErrors(0);
    setStopped(false);
    setRetryKey((key) => key + 1);
  }, []);

  return { data, error, stale, loading, consecutiveErrors, stopped, retry };
}
