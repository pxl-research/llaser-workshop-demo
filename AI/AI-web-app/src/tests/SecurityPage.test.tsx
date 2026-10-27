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

function renderSecurityPage() {
  mockFetch.mockResolvedValue({
    ok: true,
    json: async () => securityConfig,
  } as Response);

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
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
    const [url, init] = mockFetch.mock.calls[1];
    expect(url).toBe("/api/security-config");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ use_homebrew: true, use_nlp_defense: false });
  });

  it("does not show the SonarQube verification", async () => {
    renderSecurityPage();

    await screen.findByText("Prompt Defenses");
    expect(screen.queryByText(/SonarQube/)).not.toBeInTheDocument();
  });
});
