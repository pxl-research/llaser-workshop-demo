import { apiUrl } from "./api";

// Generate or retrieve session ID
const getSessionId = (): string => {
  let sessionId = sessionStorage.getItem("chat_session_id");
  if (!sessionId) {
    // getRandomValues, not randomUUID: the app is served over plain HTTP, where randomUUID is missing.
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    sessionId = `session_${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
    sessionStorage.setItem("chat_session_id", sessionId);
  }
  return sessionId;
};

const responseError = async (response: Response): Promise<Error> => {
  const generic = `API error: ${response.status}`;
  let detail = generic;
  try {
    const errorBody = (await response.json()) as { detail?: string };
    if (typeof errorBody.detail === "string" && errorBody.detail.trim() !== "") {
      detail = errorBody.detail;
    }
  } catch {
    // Keep the generic status-based message when the body is not JSON.
  }

  if (response.status === 503 && detail === generic) {
    return new Error("The AI system is still starting. Please wait until models finish loading.");
  }
  return new Error(detail);
};

const handleEvent = (event: string, onDelta: (text: string) => void) => {
  if (!event.startsWith("data: ")) return;
  const data = JSON.parse(event.slice("data: ".length)) as { delta?: string; error?: string };
  if (data.error) throw new Error(data.error);
  if (data.delta) onDelta(data.delta);
};

const readEvents = async (body: ReadableStream<Uint8Array>, onDelta: (text: string) => void) => {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const event of events) handleEvent(event, onDelta);
  }
};

// Streams the answer: onDelta gets each piece of text as the backend sends it.
export const sendMessageToAPI = async (
  question: string,
  onDelta: (text: string) => void
): Promise<void> => {
  try {
    const sessionId = getSessionId();
    
    const response = await fetch(apiUrl("api/query"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ 
        question,
        session_id: sessionId 
      }),
    });

    if (!response.ok) throw await responseError(response);
    if (!response.body) throw new Error("API returned an empty response");
    await readEvents(response.body, onDelta);
  } catch (error) {
    console.error("Error sending message:", error);
    onDelta(`\n\n${error}`);
  }
};
