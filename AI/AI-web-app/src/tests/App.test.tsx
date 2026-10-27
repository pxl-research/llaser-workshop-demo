import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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
