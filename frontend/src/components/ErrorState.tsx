import { ApiError } from "@/api/client";

/**
 * Renders a real API failure honestly. Distinguishes the platform's
 * well-known HTTP 503 "artifact not available yet" condition (every
 * read-only JSON-artifact-backed router in this platform uses it -- see
 * ADR-0009 and `control_plane.artifacts`) from an unexpected error, and
 * a 404 from either. Never swallows the error into a generic message —
 * the whole point of "do not fake backend behavior" is that a real
 * failure stays visible.
 */
export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const isApiError = error instanceof ApiError;
  const isNotYetGenerated = isApiError && error.status === 503;
  const isNotFound = isApiError && error.status === 404;

  return (
    <div className="error-state" role="alert">
      <p className="error-state__title">
        {isNotYetGenerated
          ? "Not available yet"
          : isNotFound
            ? "Not found"
            : "Something went wrong loading this data"}
      </p>
      <p className="error-state__detail">{isApiError ? error.detail : error.message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="button button--secondary">
          Retry
        </button>
      )}
    </div>
  );
}
