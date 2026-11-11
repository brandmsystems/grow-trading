import { useCallback, useEffect, useRef, useState } from "react";
import { getJob } from "../services/api";
import type { Job } from "../types/api";

/** Loads data once (and on `deps` change), with loading/error state and a reload function. */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const load = useCallback(async () => {
    const my = ++seq.current;
    setLoading(true);
    try {
      const d = await fnRef.current();
      if (my === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (my === seq.current) setError((e as Error).message);
    } finally {
      if (my === seq.current) setLoading(false);
    }
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, deps);
  return { data, error, loading, reload: load, setData };
}

/** Polls a background job until it finishes. Resolves with the final job (state done or error). */
export async function waitForJob(id: string, onProgress?: (j: Job) => void, everyMs = 1000): Promise<Job> {
  for (;;) {
    const j = await getJob(id);
    onProgress?.(j);
    if (j.state === "done" || j.state === "error") return j;
    await new Promise((r) => setTimeout(r, everyMs));
  }
}
