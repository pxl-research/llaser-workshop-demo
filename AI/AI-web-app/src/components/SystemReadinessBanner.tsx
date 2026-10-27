import { useSystemReadiness } from "./SystemReadinessContext";
import "../styles/system-readiness-banner.css";

function isConfigReload(readiness: { components: Record<string, { state: string }> } | null): boolean {
  if (!readiness) return false;
  const states = Object.values(readiness.components).map((c) => c.state);
  return states.some((s) => s === "ready") && states.some((s) => s === "loading");
}

export function SystemReadinessBanner() {
  const { readiness, isReady, isError, isLoading, statusMessage } = useSystemReadiness();

  if (isReady) {
    return null;
  }

  const reloading = isConfigReload(readiness);

  return (
    <div
      className={`system-readiness-banner ${
        isError ? "system-readiness-banner--error" : "system-readiness-banner--loading"
      }`}
      role="status"
      aria-live="polite"
    >
      <div className="system-readiness-banner__content">
        <p className="system-readiness-banner__title">
          {isError
            ? "AI system unavailable"
            : reloading
              ? "Switching model configuration"
              : "AI system is starting"}
        </p>
        <p className="system-readiness-banner__message">{statusMessage}</p>
        {isLoading && !reloading ? (
          <p className="system-readiness-banner__hint">
            The first start can take a minute. Chat is disabled until the backend is ready.
          </p>
        ) : null}
      </div>
    </div>
  );
}
