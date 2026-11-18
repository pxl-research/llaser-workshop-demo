import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import AlertsPage from "../pages/AlertsPage";
import { fetchPendingAlertCount } from "../services/alerts";
import { getSessionId } from "../services/ChatService";

const alert = (id: string, sessionID: string, status = "pending") => ({
  id,
  prompt: `prompt ${id}`,
  timestamp: "2026-11-18T10:00:00Z",
  riskLevel: "high",
  threatTypes: [],
  sessionID,
  status,
});

const stubAlerts = (alerts: unknown[]) => {
  const mockFetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ alerts }) } as Response);
  vi.stubGlobal("fetch", mockFetch);
  return mockFetch;
};

describe("AlertsPage", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("clears the fetch error once the backend answers again", async () => {
    vi.useFakeTimers();
    const mockFetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: false } as Response)
      .mockResolvedValue({ ok: true, json: async () => ({ alerts: [] }) } as Response);
    vi.stubGlobal("fetch", mockFetch);

    render(<AlertsPage />);
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("Failed to fetch alerts")).toBeInTheDocument();

    // The page polls every 10 s; a backend restart must not leave a stale error.
    await act(() => vi.advanceTimersByTimeAsync(10000));
    expect(screen.queryByText("Failed to fetch alerts")).not.toBeInTheDocument();
  });

  it("explains what Accept and Deny do", async () => {
    stubAlerts([]);
    render(<AlertsPage />);
    expect(screen.getByRole("heading", { name: "Alerts" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "A defense blocked these questions. Accept: the chat model answers, in the chat that asked. Deny: the question is dropped. Both unblock that chat."
      )
    ).toBeInTheDocument();
  });

  it("hides red-team run alerts until the checkbox is ticked", async () => {
    stubAlerts([alert("a1", "session_x"), alert("a2", "promptfoo-redteam-1"), alert("a3", "promptfoo-redteam-2")]);
    render(<AlertsPage />);

    expect(await screen.findByText("prompt a1")).toBeInTheDocument();
    expect(screen.queryByText("prompt a2")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pending (1)" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "Show red-team run alerts (2)" }));
    expect(screen.getByText("prompt a2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pending (3)" })).toBeInTheDocument();
  });

  it("does not flicker the Refresh button on the background poll", async () => {
    vi.useFakeTimers();
    let resolveSecond: (value: Response) => void = () => {};
    const mockFetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ alerts: [] }) } as Response)
      .mockImplementationOnce(() => new Promise<Response>((resolve) => (resolveSecond = resolve)));
    vi.stubGlobal("fetch", mockFetch);

    render(<AlertsPage />);
    await act(() => vi.advanceTimersByTimeAsync(0));
    await act(() => vi.advanceTimersByTimeAsync(10000));
    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();
    await act(async () => resolveSecond({ ok: true, json: async () => ({ alerts: [] }) } as Response));
  });

  it("names where the question was asked instead of the raw session id", async () => {
    const own = getSessionId();
    stubAlerts([alert("a1", own), alert("a2", "promptfoo-redteam-x"), alert("a3", "session_other")]);
    render(<AlertsPage />);

    expect(await screen.findByText("this tab")).toBeInTheDocument();
    expect(screen.getByText("another tab")).toBeInTheDocument();
    expect(screen.queryByText(own)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: /Show red-team run alerts/ }));
    expect(screen.getByText("a red-team run")).toBeInTheDocument();
  });

  it("shows no risk badge", async () => {
    stubAlerts([alert("a1", "session_x")]);
    render(<AlertsPage />);
    await screen.findByText("prompt a1");
    expect(screen.queryByText("HIGH")).not.toBeInTheDocument();
  });
});

describe("fetchPendingAlertCount", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("skips red-team run alerts", async () => {
    stubAlerts([
      alert("a1", "session_x"),
      alert("a2", "promptfoo-redteam-1"),
      alert("a3", "session_x", "accepted"),
      { id: "a4", status: "pending" },
    ]);
    await expect(fetchPendingAlertCount()).resolves.toBe(2);
  });
});
