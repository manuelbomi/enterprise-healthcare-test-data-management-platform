import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/client";

export interface ApiDataState<T> {
  data: T | null;
  loading: boolean;
  /** `null` when there was no error; a plain `Error` (usually an
   * `ApiError`) otherwise. Pages branch on `error instanceof ApiError &&
   * error.status === 503` to render the platform's well-known "artifact
   * not available yet" condition distinctly from an unexpected failure. */
  error: Error | null;
  reload: () => void;
}

/**
 * Fetches data from a typed `@/api` function on mount (and whenever
 * `deps` changes), tracking loading/error state so pages don't each
 * hand-roll the same `useEffect` + `useState` boilerplate. Every page in
 * this console composes this hook with a real `@/api/*` call — never
 * fabricated/mocked data (see `docs/adr/0008-frontend-stack.md`).
 *
 * Not a generic data-fetching *library* (no caching, no request
 * dedup) — deliberately minimal for a console this size; see
 * `problems_phase_09.md` if that stops being true.
 */
export function useApiData<T>(fetcher: () => Promise<T>, deps: React.DependencyList = []): ApiDataState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcherRef
      .current()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err : new ApiError(0, String(err)));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken, ...deps]);

  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  return { data, loading, error, reload };
}
