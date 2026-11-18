import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SecurityPage from "../pages/SecurityPage";

const mockFetch = vi.fn();

const securityConfig = {
  use_homebrew: false,
  use_nlp_defense: false,
  homebrew_status: "off" as const,
  nlp_defense_status: "off" as const,
  nlp_confidence_threshold: 0.8,
  safe_answer_rendering: false,
};

function renderSecurityPage(overrides: Record<string, unknown> = {}) {
  const bodies: Record<string, unknown> = {
    "/api/security-config": { ...securityConfig, ...overrides },
    "/api/available-llms": [],
    "/api/llm": { llm: "test/model" },
    "/api/system-prompt": { prompt: "{context}", default_prompt: "{context}" },
  };
  mockFetch.mockImplementation(async (url: string) => ({ ok: true, json: async () => bodies[url] }) as Response);

  return render(<SecurityPage />);
}

describe("SecurityPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(() => {
    cleanup();
    mockFetch.mockReset();
    vi.stubGlobal("fetch", mockFetch);
  });

  it("applies a ticked defense at once, without an Apply button", async () => {
    renderSecurityPage();

    fireEvent.click(await screen.findByRole("checkbox", { name: /^LLM defense/ }));

    await waitFor(() => {
      expect(mockFetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    });
    const [url, init] = mockFetch.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(url).toBe("/api/security-config");
    expect(JSON.parse(init.body)).toEqual({ use_homebrew: true });
    expect(screen.queryByRole("button", { name: "Apply changes" })).not.toBeInTheDocument();
    expect(screen.getByText("Every change applies at once and lasts until the app restarts.")).toBeInTheDocument();
  });

  it("applies the NLP defense at once", async () => {
    renderSecurityPage();

    fireEvent.click(await screen.findByRole("checkbox", { name: /^NLP defense/ }));

    await waitFor(() => {
      const post = mockFetch.mock.calls.find(([, init]) => init?.method === "POST");
      expect(JSON.parse(post![1].body)).toEqual({ use_nlp_defense: true });
    });
  });

  it("disables only the defense that is loading", async () => {
    renderSecurityPage({ use_nlp_defense: true, nlp_defense_status: "loading" });

    expect(await screen.findByRole("checkbox", { name: /^NLP defense/ })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /^LLM defense/ })).toBeEnabled();
  });

  it("puts the prompt defenses first", async () => {
    renderSecurityPage();

    await screen.findByRole("heading", { name: "Chat Model" });
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Prompt Defenses",
      "System Prompt",
      "Chat Model",
      "Answer Rendering",
    ]);
  });

  it("shows a defense error under its own row", async () => {
    renderSecurityPage({ use_homebrew: true, homebrew_status: "error", homebrew_error: "Spark and OpenRouter failed" });

    const message = await screen.findByText("Spark and OpenRouter failed");
    const row = message.closest(".defense-item") as HTMLElement;
    expect(row).toContainElement(screen.getByRole("checkbox", { name: /^LLM defense/ }));
  });

  it("explains the threshold, and how to use it while the NLP defense is off", async () => {
    renderSecurityPage();
    expect(await screen.findByText("Switch on the NLP defense to use the threshold.")).toBeInTheDocument();

    cleanup();
    renderSecurityPage({ use_nlp_defense: true, nlp_defense_status: "ready" });
    expect(
      await screen.findByText(
        "A question is blocked when its NLP score is at or above this value. Lower: blocks more, also harmless questions. Higher: lets more attacks through."
      )
    ).toBeInTheDocument();
  });

  it("describes both defenses", async () => {
    renderSecurityPage({ nlp_model_version: "v1" });

    expect(
      await screen.findByText(
        "A small classifier (DistilBERT) on this laptop gives each question a score from 0 to 1. Model v1."
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "A Qwen model on the PXL DGX Spark labels each question safe or malicious. If the Spark is unreachable, a Qwen model on OpenRouter takes over."
      )
    ).toBeInTheDocument();
  });

  it("shows the chat model and system prompt sections", async () => {
    renderSecurityPage();

    expect(await screen.findByRole("heading", { name: "Chat Model" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "System Prompt" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Controls" })).toBeInTheDocument();
  });

  it("shows when the LLM defense runs on the OpenRouter fallback", async () => {
    renderSecurityPage({ use_homebrew: true, homebrew_status: "ready", homebrew_backend: "openrouter" });

    expect(await screen.findByText("Active (OpenRouter fallback)")).toBeInTheDocument();
  });

  it("shows a plain Active badge when the LLM defense runs on the Spark", async () => {
    renderSecurityPage({ use_homebrew: true, homebrew_status: "ready", homebrew_backend: "spark" });

    expect(await screen.findByText("Active")).toBeInTheDocument();
    expect(screen.queryByText(/OpenRouter fallback/)).not.toBeInTheDocument();
  });

  it("switches safe answer rendering on at once, without Apply", async () => {
    renderSecurityPage();

    const toggle = await screen.findByRole("checkbox", { name: /Safe answer rendering/ });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(mockFetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    });
    const [url, init] = mockFetch.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(url).toBe("/api/security-config");
    expect(JSON.parse(init.body)).toEqual({ safe_answer_rendering: true });
    expect(screen.queryByRole("button", { name: "Apply changes" })).not.toBeInTheDocument();
  });

  it("shows safe answer rendering as Active when it is on", async () => {
    renderSecurityPage({ safe_answer_rendering: true });

    expect(await screen.findByRole("checkbox", { name: /Safe answer rendering/ })).toBeChecked();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("does not show the SonarQube verification", async () => {
    renderSecurityPage();

    await screen.findByText("Prompt Defenses");
    expect(screen.queryByText(/SonarQube/)).not.toBeInTheDocument();
  });

  it("shows the NLP model version", async () => {
    renderSecurityPage({ nlp_model_version: "v1" });

    expect(await screen.findByText(/Model v1\./)).toBeInTheDocument();
  });
});
