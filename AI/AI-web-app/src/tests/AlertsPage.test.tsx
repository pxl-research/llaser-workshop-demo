import { act, cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import AlertsPage from "../pages/AlertsPage";

describe("AlertsPage", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
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
});
