"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/**
 * Load data on mount (and when deps change), with loading / error state and a reload function.
 * Responses from superseded requests are discarded, so a slow earlier request can never
 * overwrite the result of a newer one (e.g. when filters change quickly).
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  const requestId = useRef(0);

  useLayoutEffect(() => {
    fnRef.current = fn;
  });

  const run = useCallback((onDone?: () => void) => {
    const id = ++requestId.current;
    fnRef.current().then(
      (d) => {
        if (id !== requestId.current) return;
        setData(d);
        setError(null);
      },
      (e: unknown) => {
        if (id !== requestId.current) return;
        setError((e as Error).message);
      },
    ).finally(() => {
      if (id === requestId.current) setLoading(false);
      onDone?.();
    });
  }, []);

  const reload = useCallback(
    (silent = false) =>
      new Promise<void>((resolve) => {
        if (!silent) setLoading(true);
        run(resolve);
      }),
    [run],
  );

  useEffect(() => {
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- callers pass their own dependency list
  }, deps);

  return { data, error, loading, reload, setData };
}
