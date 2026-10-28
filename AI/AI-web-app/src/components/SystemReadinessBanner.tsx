import { useSystemReadiness } from "./SystemReadinessContext";
import "../styles/system-readiness-banner.css";

export function SystemReadinessBanner() {
  const { isReady, isError, isLoading, statusMessage } = useSystemReadiness();

  if (isReady) {
    return null;
  }

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
          {isError ? "AI system unavailable" : "AI system is starting"}
        </p>
        <p className="system-readiness-banner__message">{statusMessage}</p>
        {isLoading ? (
          <p className="system-readiness-banner__hint">
            The first start can take a minute. Chat is disabled until the backend is ready.
          </p>
        ) : null}
      </div>
    </div>
  );
}
