import type { ReactNode } from "react";
import type { ApiDataState } from "@/hooks/useApiData";
import { ErrorState } from "./ErrorState";
import { LoadingState } from "./LoadingState";

/**
 * Renders the three states every `useApiData` call can be in
 * (loading / error / real data), so pages compose this instead of
 * repeating the same `if (loading) ... if (error) ...` branch at every
 * call site. `state.data` is guaranteed non-null inside `children` (the
 * loading/error branches already returned).
 */
export function AsyncSection<T>({
  state,
  children,
  loadingLabel,
}: {
  state: ApiDataState<T>;
  children: (data: T) => ReactNode;
  loadingLabel?: string;
}) {
  if (state.loading) return <LoadingState label={loadingLabel} />;
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />;
  if (state.data === null) return <ErrorState error={new Error("No data returned.")} onRetry={state.reload} />;
  return <>{children(state.data)}</>;
}
