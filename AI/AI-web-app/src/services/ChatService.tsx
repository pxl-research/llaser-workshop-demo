
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

type OnDelta = (text: string) => void;

// One server-sent event from the backend: a piece of the answer, an error, or the alert of a blocked question.
interface AnswerEvent {
  delta?: string;
  error?: string;
  alert_id?: string;
}

export interface AnswerResult {
  // Set when a defense blocked the question; the alert waits for review on the Alerts page.
  alertId: string | null;
}

// The backend streams events as "data: {...}" blocks separated by a blank line.
const readEvents = async (body: ReadableStream<Uint8Array>, onEvent: (event: AnswerEvent) => void) => {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? ""; // the last block may still be incomplete
    for (const block of blocks) {
      if (block.startsWith("data: ")) onEvent(JSON.parse(block.slice("data: ".length)) as AnswerEvent);
    }
  }
};

// POSTs to the backend and passes each piece of the answer to onDelta as it arrives.
// Errors are shown in the answer itself.
const streamAnswer = async (url: string, body: object, onDelta: OnDelta): Promise<AnswerResult> => {
  const result: AnswerResult = { alertId: null };
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw await responseError(response);
    if (!response.body) throw new Error("API returned an empty response");

    await readEvents(response.body, (event) => {
      if (event.error) throw new Error(event.error);
      if (event.delta) onDelta(event.delta);
      if (event.alert_id) result.alertId = event.alert_id;
    });
  } catch (error) {
    console.error("Error sending message:", error);
    onDelta(`\n\n${error}`);
  }
  return result;
};

export const sendMessageToAPI = (question: string, onDelta: OnDelta): Promise<AnswerResult> =>
  streamAnswer("/api/query", { question, session_id: getSessionId() }, onDelta);

// "gone": the backend no longer knows the alert, e.g. after a restart.
export type AlertStatus = "pending" | "accepted" | "denied" | "gone";

const alertUrl = (alertId: string) => `/api/prompt-alerts/${encodeURIComponent(alertId)}`;

export const fetchAlertStatus = async (alertId: string): Promise<AlertStatus> => {
  const response = await fetch(alertUrl(alertId));
  if (response.status === 404) return "gone";
  if (!response.ok) throw await responseError(response);
  return ((await response.json()) as { status: AlertStatus }).status;
};

// Streams the answer to a prompt a reviewer accepted; only this session gets it, once.
export const fetchAcceptedAnswer = async (alertId: string, onDelta: OnDelta): Promise<void> => {
  await streamAnswer(`${alertUrl(alertId)}/release`, { session_id: getSessionId() }, onDelta);
};
