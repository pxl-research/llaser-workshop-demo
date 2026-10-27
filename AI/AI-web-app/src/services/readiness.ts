import { apiUrl } from "./api";

export type ComponentState = "pending" | "loading" | "ready" | "skipped" | "error";

export type ReadinessStatus = "pending" | "loading" | "ready" | "error";

export type ReadinessComponent = {
  state: ComponentState;
  model?: string;
  message?: string;
};

export type ReadinessResponse = {
  status: ReadinessStatus;
  components: Record<string, ReadinessComponent>;
  message?: string;
};

const COMPONENT_LABELS: Record<string, string> = {
  embedding: "Embedding model",
  reranker: "Reranker",
  vector_store: "Document index",
  llm: "Language model",
  system: "AI system",
};

export const fetchReadiness = async (): Promise<ReadinessResponse> => {
  const response = await fetch(apiUrl("api/ready"));

  if (!response.ok) {
    throw new Error(`Readiness check failed (${response.status})`);
  }

  const payload = (await response.json()) as ReadinessResponse;
  return payload;
};

export const isBackendStartupFailure = (readiness: ReadinessResponse | null): boolean =>
  readiness?.status === "error";

export const describeReadiness = (readiness: ReadinessResponse | null): string => {
  if (!readiness) {
    return "Checking whether the AI system is ready...";
  }

  if (readiness.status === "ready") {
    return "AI system is ready.";
  }

  if (readiness.status === "error") {
    return readiness.message ?? "The AI system failed to start.";
  }

  const activeComponent = Object.entries(readiness.components).find(([, component]) =>
    ["loading", "pending"].includes(component.state)
  );

  if (!activeComponent) {
    return "Preparing the AI system. This can take a few minutes on first run.";
  }

  const [name, component] = activeComponent;
  const label = COMPONENT_LABELS[name] ?? name;
  const modelSuffix = component.model ? ` (${component.model})` : "";

  if (component.state === "loading") {
    return `Loading ${label.toLowerCase()}${modelSuffix}...`;
  }

  return `Waiting to load ${label.toLowerCase()}${modelSuffix}...`;
};
