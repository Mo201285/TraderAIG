import { useEffect, useState } from "react";
import { api } from "./api";

export interface AsyncData<T> {
  data: T | null;
  source: "live" | "mock" | "loading";
  error?: string;
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
