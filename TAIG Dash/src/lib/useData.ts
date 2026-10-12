import { useEffect, useState } from "react";
import { api } from "./api";

export interface AsyncData<T> {
  data: T | null;
  source: "live" | "mock" | "loading";
  error?: string;
}

export interface BackendStatus {
  reachable: boolean;
  loading: boolean;
  overall: string;
  lastSync: number | null;
  error?: string;
}

/**
 * One provenance source for the whole shell: is the backend answering, what is
 * its overall health, and when did we last hear from it. Polled so the UI can
 * never leave a stale green light on screen after the backend drops.
 */
export function useBackendStatus(pollMs = 15000): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>({
    reachable: false,
    loading: true,
    overall: "unknown",
    lastSync: null,
  });
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const env = await api.getSystemHealth();
      if (!alive) return;
      const ok = env.ok && env.source === "live";
      setStatus((prev) => ({
        reachable: ok,
        loading: false,
        overall: ok ? env.data?.overall ?? "unknown" : "offline",
        lastSync: ok ? Date.now() : prev.lastSync,
        error: env.error,
      }));
    };
    tick();
    const id = setInterval(tick, pollMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [pollMs]);
  return status;
}

export function useData<T>(
  loader: () => Promise<{ ok: boolean; data: T; source: "live" | "mock"; error?: string }>,
  version: number = 0,
): AsyncData<T> {
  const [state, setState] = useState<AsyncData<T>>({ data: null, source: "loading" });

  useEffect(() => {
    let cancelled = false;
    loader().then((res) => {
      if (cancelled) return;
      setState({ data: res.data, source: res.source, error: res.error });
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  return state;
}

export { api };
