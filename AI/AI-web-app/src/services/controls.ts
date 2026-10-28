
type SystemPrompt = { prompt: string; default_prompt: string };

export type LlmModel = {
  id: string;
  name: string;
  context_length?: number | null;
  prompt_price: string | null;
  completion_price: string | null;
};

export const errorDetail = async (response: Response, fallback: string) => {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch { /* ignore */ }
  return `${fallback} (${response.status})`;
};

const getJson = async <T>(path: string, fallback: string): Promise<T> => {
  const response = await fetch(path);
  if (!response.ok) throw new Error(await errorDetail(response, fallback));
  return (await response.json()) as T;
};

const postJson = async <T>(path: string, body: unknown, fallback: string): Promise<T> => {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await errorDetail(response, fallback));
  return (await response.json()) as T;
};

export const fetchSystemPrompt = () =>
  getJson<SystemPrompt>("/api/system-prompt", "Failed to load the system prompt");

export const updateSystemPrompt = (prompt: string | null) =>
  postJson<SystemPrompt>("/api/system-prompt", { prompt }, "Failed to apply the system prompt");

export const fetchModels = async () =>
  (await getJson<LlmModel[]>("/api/available-llms", "Failed to load the model list")).sort(
    (a, b) => Number(a.prompt_price ?? 0) - Number(b.prompt_price ?? 0)
  );

export const fetchCurrentModel = async () =>
  (await getJson<{ llm: string }>("/api/llm", "Failed to load the current model")).llm;

export const updateModel = (id: string) =>
  postJson<{ llm: string }>("/api/llm", { llm: id }, "Failed to switch the model");

// OpenRouter prices are per token, as strings.
export const pricePerMillion = (price: string | null) =>
  price == null ? "?" : `$${(Number(price) * 1e6).toFixed(2)}`;
