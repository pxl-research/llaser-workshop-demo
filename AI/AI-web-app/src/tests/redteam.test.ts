import { afterEach, describe, expect, it, vi } from "vitest";
import { answersUrl, fetchRedteamRuns, reportUrl } from "../services/redteam";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

const jsonResponse = (status: number, body: unknown) =>
  ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response;

describe("fetchRedteamRuns", () => {
  afterEach(() => mockFetch.mockReset());

  it("loads the runs from the backend and builds the promptfoo URL on the same host", async () => {
    const run = { id: "eval-1", name: "baseline", created_at: 1, attack_set: "workshop", settings: {}, attacks: 72, got_through: 5, errors: 0 };
    mockFetch.mockResolvedValueOnce(jsonResponse(200, { runs: [run], promptfoo_ui_port: 3002 }));

    const result = await fetchRedteamRuns();

    expect(mockFetch).toHaveBeenCalledWith("/api/redteam/runs");
    expect(result.runs).toEqual([run]);
    // The tests run on http://localhost:3000; nginx only accepts the host name LLASER is opened on.
    expect(result.promptfooUrl).toBe(`http://${window.location.hostname}:3002`);
  });

  it("passes on the backend's explanation when promptfoo is not running", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(503, { detail: "promptfoo is not running. Start it with: docker compose up -d" }));

    await expect(fetchRedteamRuns()).rejects.toThrow("promptfoo is not running");
  });

  it("falls back to the HTTP status when the error is not JSON", async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 502, json: async () => { throw new SyntaxError("html"); } } as unknown as Response);

    await expect(fetchRedteamRuns()).rejects.toThrow("HTTP 502");
  });
});

describe("links into the promptfoo UI", () => {
  it("encodes the run id", () => {
    expect(reportUrl("http://127.0.0.1:3002", "eval-1/x?y")).toBe("http://127.0.0.1:3002/reports?evalId=eval-1%2Fx%3Fy");
    expect(answersUrl("http://127.0.0.1:3002", "eval-1/x?y")).toBe("http://127.0.0.1:3002/eval/eval-1%2Fx%3Fy");
  });
});
