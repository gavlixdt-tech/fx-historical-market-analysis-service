import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, NetworkError, TimeoutError } from "@/services/api";
import type {
  ReadyResponseData,
  StatusResponseData,
  VersionResponseData,
} from "@/schemas/api";

interface ServiceStatusState {
  status: StatusResponseData | null;
  readiness: ReadyResponseData | null;
  version: VersionResponseData | null;
  isLoading: boolean;
  error: ApiError | null;
  lastRefreshedAt: Date | null;
  refresh: () => void;
}

/**
 * Loads the operational state of the backend.
 *
 * The three requests are issued independently so that a failure of one does
 * not hide the others. The first error encountered is surfaced; the last
 * successful refresh time is tracked separately.
 */
export function useServiceStatus(): ServiceStatusState {
  const [status, setStatus] = useState<StatusResponseData | null>(null);
  const [readiness, setReadiness] = useState<ReadyResponseData | null>(null);
  const [version, setVersion] = useState<VersionResponseData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refresh = useCallback(() => {
    setReloadToken((token) => token + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let firstError: ApiError | null = null;

    setIsLoading(true);

    const handle = async <T,>(
      promise: Promise<T>,
      apply: (value: T) => void,
    ): Promise<void> => {
      try {
        const value = await promise;
        if (!mountedRef.current || controller.signal.aborted) return;
        apply(value);
        setLastRefreshedAt(new Date());
      } catch (caught) {
        if (!mountedRef.current || controller.signal.aborted) return;
        if (firstError === null) {
          firstError = normaliseError(caught);
        }
      }
    };

    void Promise.all([
      handle(api.getStatus({ signal: controller.signal }), setStatus),
      handle(api.getReady({ signal: controller.signal }), setReadiness),
      handle(api.getVersion({ signal: controller.signal }), setVersion),
    ]).then(() => {
      if (!mountedRef.current || controller.signal.aborted) return;
      setError(firstError);
      setIsLoading(false);
    });

    return () => controller.abort();
  }, [reloadToken]);

  return { status, readiness, version, isLoading, error, lastRefreshedAt, refresh };
}

function normaliseError(caught: unknown): ApiError {
  if (caught instanceof ApiError) return caught;
  if (caught instanceof TimeoutError) return caught;
  if (caught instanceof NetworkError) return caught;
  return new ApiError(
    "An unexpected error occurred while contacting the backend.",
    0,
    "UNEXPECTED",
    null,
  );
}
