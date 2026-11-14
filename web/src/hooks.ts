import { useCallback, useEffect, useRef, useState } from "react";

export function useResource<T>(fetcher: () => Promise<T>, key: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const latest = useRef(fetcher);
  latest.current = fetcher;
  const generation = useRef(0);
  const reload = useCallback(async (quiet = false) => {
    const current = ++generation.current;
    if (!quiet) setLoading(true);
    setError(null);
    try {
      const result = await latest.current();
      if (current === generation.current) setData(result);
    } catch (e) {
      if (current === generation.current)
        setError(
          e instanceof Error ? e.message : "Could not load this record.",
        );
    } finally {
      if (current === generation.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    setData(null);
    void reload();
    return () => {
      generation.current++;
    };
  }, [key, reload]);
  return { data, error, loading, reload };
}
