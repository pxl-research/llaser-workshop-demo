import { describe, it, expect, vi, beforeEach } from "vitest";
import { sendMessageToAPI } from "../services/ChatService";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);
const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

const streamOf = (...chunks: string[]) =>
  new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
      controller.close();
    },
  });

const event = (payload: object) => `data: ${JSON.stringify(payload)}\n\n`;

const okResponse = (...chunks: string[]) =>
  ({ ok: true, status: 200, body: streamOf(...chunks) }) as unknown as Response;

const collect = async (question: string) => {
  const pieces: string[] = [];
  await sendMessageToAPI(question, (delta) => pieces.push(delta));
  return pieces;
};

describe("sendMessageToAPI", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    consoleErrorSpy.mockClear();
    sessionStorage.clear();
    vi.stubEnv("VITE_API_URL", "http://localhost:8080/");
  });

  it("sends the correct POST request and passes each streamed piece on", async () => {
    mockFetch.mockResolvedValueOnce(okResponse(event({ delta: "Hello " }), event({ delta: "from API" })));

    const pieces = await collect("What is the answer?");

    expect(pieces).toEqual(["Hello ", "from API"]);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8080/api/query",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: expect.any(String),
      })
    );
    expect(JSON.parse(mockFetch.mock.calls[0][1].body)).toEqual({
      question: "What is the answer?",
      session_id: expect.stringMatching(/^session_[0-9a-f]{32}$/),
    });
  });

  it("handles events split across network chunks", async () => {
    const whole = event({ delta: "split" }) + event({ delta: " event" });
    mockFetch.mockResolvedValueOnce(okResponse(whole.slice(0, 9), whole.slice(9, 30), whole.slice(30)));

    expect(await collect("hi")).toEqual(["split", " event"]);
  });

  it("creates a session id on plain-HTTP pages, where crypto.randomUUID is missing", async () => {
    vi.stubGlobal("crypto", { getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto) });
    mockFetch.mockResolvedValueOnce(okResponse(event({ delta: "ok" })));

    try {
      await collect("hi");
    } finally {
      vi.unstubAllGlobals();
      vi.stubGlobal("fetch", mockFetch);
    }

    expect(JSON.parse(mockFetch.mock.calls[0][1].body).session_id).toMatch(/^session_[0-9a-f]{32}$/);
  });

  it("shows an error event from the backend", async () => {
    mockFetch.mockResolvedValueOnce(
      okResponse(event({ delta: "partial" }), event({ error: "Query processing failed" }))
    );

    const pieces = await collect("hi");
    expect(pieces[0]).toBe("partial");
    expect(pieces.join("")).toContain("Query processing failed");
  });

  it("returns a friendly message when the backend is still starting", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: () => Promise.resolve({ detail: "System is still starting" }),
    } as Response);

    expect((await collect("hi")).join("")).toContain("System is still starting");
  });

  it("returns error message when response.ok is false", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: () => Promise.resolve({}),
    } as Response);

    expect((await collect("Cause an error")).join("")).toContain("API error: 500");
    expect(consoleErrorSpy).toHaveBeenCalledWith("Error sending message:", expect.any(Error));
  });

  it("returns error message when fetch throws", async () => {
    mockFetch.mockRejectedValueOnce(new Error("Network down"));

    expect((await collect("Any question")).join("")).toContain("Network down");
    expect(consoleErrorSpy).toHaveBeenCalledWith("Error sending message:", expect.any(Error));
  });
});
