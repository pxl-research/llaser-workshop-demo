import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi, beforeEach } from "vitest";
import App from "../App";

vi.mock("../pages/ChatPage.tsx", () => ({
  default: () => (
    <div>
      <div>Chat page content</div>
      <input aria-label="chat draft" />
    </div>
  ),
}));

vi.mock("../pages/SecurityPage.tsx", () => ({
  default: () => <div>Security page content</div>,
}));

vi.mock("../pages/AlertsPage.tsx", () => ({
  default: () => <div>Alerts page content</div>,
}));

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("App shell", () => {
  afterEach(() => {
    cleanup();
    mockFetch.mockReset();
  });

  beforeEach(() => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ status: "ready", components: {} }),
    } as Response);
  });

  it("renders the header branding and chat page by default", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "LLASER" })).toBeInTheDocument();
    expect(within(screen.getByRole("banner")).queryAllByRole("img")).toHaveLength(0);
    expect(screen.getByText("Chat page content")).toBeInTheDocument();
  });

  it("switches between Chat, Controls, and Alerts pages", () => {
    render(<App />);

    expect(screen.queryByRole("button", { name: "Model Configuration" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Controls" }));
    expect(screen.getByText("Security page content")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Alerts" }));
    expect(screen.getByText("Alerts page content")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Chat" }));
    expect(screen.getByText("Chat page content")).toBeInTheDocument();
  });

  describe("pending alerts badge", () => {
    const alertsWith = (...statuses: string[]) =>
      mockFetch.mockImplementation(async (url: string) =>
        url === "/api/prompt-alerts"
          ? ({ ok: true, json: async () => ({ alerts: statuses.map((status, i) => ({ id: `a${i}`, status })) }) } as Response)
          : ({ ok: true, json: async () => ({ status: "ready", components: {} }) } as Response)
      );

    afterEach(() => {
      vi.useRealTimers();
    });

    it("shows the number of pending alerts on the Alerts button", async () => {
      alertsWith("pending", "accepted", "pending", "denied");
      render(<App />);

      const button = await screen.findByRole("button", { name: "Alerts (2 pending)" });
      expect(within(button).getByText("2")).toHaveClass("nav-badge");
    });

    it("shows no badge without pending alerts", async () => {
      alertsWith("accepted", "denied");
      render(<App />);

      await vi.waitFor(() => expect(mockFetch).toHaveBeenCalledWith("/api/prompt-alerts"));
      const button = screen.getByRole("button", { name: "Alerts" });
      expect(button.querySelector(".nav-badge")).toBeNull();
    });

    it("caps the badge at 99+", async () => {
      alertsWith(...Array.from({ length: 120 }, () => "pending"));
      render(<App />);

      const button = await screen.findByRole("button", { name: "Alerts (120 pending)" });
      expect(within(button).getByText("99+")).toBeInTheDocument();
    });

    it("updates the count and keeps it while the backend is unreachable", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      alertsWith("pending");
      render(<App />);
      await screen.findByRole("button", { name: "Alerts (1 pending)" });

      mockFetch.mockRejectedValue(new Error("backend restarting"));
      await act(() => vi.advanceTimersByTimeAsync(5000));
      expect(screen.getByRole("button", { name: "Alerts (1 pending)" })).toBeInTheDocument();

      alertsWith("pending", "pending", "pending");
      await act(() => vi.advanceTimersByTimeAsync(5000));
      expect(await screen.findByRole("button", { name: "Alerts (3 pending)" })).toBeInTheDocument();
    });
  });

  it("preserves chat state when switching to another page and back", () => {
    render(<App />);

    const chatDraft = screen.getByLabelText("chat draft");
    fireEvent.change(chatDraft, { target: { value: "keep this draft" } });

    fireEvent.click(screen.getByRole("button", { name: "Controls" }));
    expect(screen.getByText("Security page content")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Chat" }));
    expect(screen.getByLabelText("chat draft")).toHaveValue("keep this draft");
  });
});
