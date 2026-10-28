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
  max_upload_size_mb: 10,
  max_output_tokens: 1024,
  provider_timeout_seconds: 30,
  static_code_analysis_verified: false,
};

function renderSecurityPage(overrides: Record<string, unknown> = {}) {
  const bodies: Record<string, unknown> = {
    "/api/security-config": { ...securityConfig, ...overrides },
    "/api/available-llms": [],
    "/api/current-config": { status: "success", config: { llm: "test/model" } },
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

  it("applies a toggled defense with a POST to the security config", async () => {
    renderSecurityPage();

    fireEvent.click(await screen.findByRole("checkbox", { name: /LLM-based defense/ }));
    fireEvent.click(screen.getByRole("button", { name: "Apply changes" }));

    await waitFor(() => {
      expect(mockFetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    });
    const [url, init] = mockFetch.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(url).toBe("/api/security-config");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ use_homebrew: true, use_nlp_defense: false });
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

  it("does not show the SonarQube verification", async () => {
    renderSecurityPage();

    await screen.findByText("Prompt Defenses");
    expect(screen.queryByText(/SonarQube/)).not.toBeInTheDocument();
  });
});
