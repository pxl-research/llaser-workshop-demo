import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  describeReadiness,
  fetchReadiness,
  isBackendStartupFailure,
  type ReadinessResponse,
} from "../services/readiness";

const READY_POLL_INTERVAL_MS = 5000;
const LOADING_POLL_INTERVAL_MS = 2000;

type SystemReadinessContextValue = {
  isReady: boolean;
  isError: boolean;
  isLoading: boolean;
  statusMessage: string;
};

const CONNECTING_MESSAGE = "Checking AI system status...";
const BACKEND_UNAVAILABLE_MESSAGE =
  "Could not reach the backend readiness endpoint. Retrying...";

const SystemReadinessContext = createContext<SystemReadinessContextValue | null>(null);

export function SystemReadinessProvider({ children }: { children: ReactNode }) {
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const nextReadiness = await fetchReadiness();
      setReadiness(nextReadiness);
      setFetchError(null);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : BACKEND_UNAVAILABLE_MESSAGE;
      setFetchError(message);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const isReady = readiness?.status === "ready";
  const isError = isBackendStartupFailure(readiness);
  const isLoading = !isReady && !isError;

  useEffect(() => {
    if (isReady || isError) {
      return;
    }

    const intervalMs = readiness ? LOADING_POLL_INTERVAL_MS : READY_POLL_INTERVAL_MS;
    const intervalId = window.setInterval(() => {
      void refresh();
    }, intervalMs);

    return () => window.clearInterval(intervalId);
  }, [isReady, isError, readiness?.status, fetchError]);

  const statusMessage = isBackendStartupFailure(readiness)
    ? describeReadiness(readiness)
    : fetchError
      ? BACKEND_UNAVAILABLE_MESSAGE
      : readiness
        ? describeReadiness(readiness)
        : CONNECTING_MESSAGE;

  const value = useMemo(
    () => ({ isReady, isError, isLoading, statusMessage }),
    [isReady, isError, isLoading, statusMessage]
  );

  return (
    <SystemReadinessContext.Provider value={value}>{children}</SystemReadinessContext.Provider>
  );
}

export const useSystemReadiness = (): SystemReadinessContextValue => {
  const context = useContext(SystemReadinessContext);
  if (!context) {
    throw new Error("useSystemReadiness must be used within SystemReadinessProvider");
  }
  return context;
};
