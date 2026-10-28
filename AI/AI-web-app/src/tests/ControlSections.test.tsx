import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ModelSection, SystemPromptSection } from "../pages/ControlSections";

const mockFetch = vi.fn();
const ok = (body: unknown) => ({ ok: true, json: async () => body }) as Response;

const routes: Record<string, unknown> = {
  "/api/system-prompt": { prompt: "Active {context}", default_prompt: "Default {context}" },
  "/api/current-config": { status: "success", config: { llm: "cheap/model" } },
  "/api/available-llms": [
    { id: "pricey/model", name: "Pricey", prompt_price: "0.000003", completion_price: "0.000015" },
    { id: "cheap/model", name: "Cheap", prompt_price: "0.0000001", completion_price: "0.0000003" },
  ],
};

function serve(url: string, init?: RequestInit) {
  if (init?.method !== "POST") return ok(routes[url]);
  if (url === "/api/system-prompt") {
    const prompt = JSON.parse(String(init.body)).prompt ?? "Default {context}";
    return ok({ prompt, default_prompt: "Default {context}" });
  }
  return ok({ status: "success" });
}

describe("control sections", () => {
  beforeEach(() => {
    mockFetch.mockImplementation(async (url: string, init?: RequestInit) => serve(url, init));
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(() => {
    cleanup();
    mockFetch.mockReset();
  });

  it("shows the current model with its price per 1M tokens", async () => {
    render(<ModelSection />);

    await waitFor(() =>
      expect(screen.getByText(/Current:/).textContent).toContain(
        "cheap/model ($0.10 in / $0.30 out per 1M tokens)"
      )
    );
  });

  it("switches the model with a POST to update-config", async () => {
    render(<ModelSection />);
    await waitFor(() => expect(screen.getByText(/Current:/).textContent).toContain("($0.10"));

    fireEvent.click(screen.getByLabelText("Select Pricey"));
    fireEvent.click(screen.getByRole("button", { name: "Use this model" }));

    await waitFor(() => expect(screen.getByText(/Current:/).textContent).toContain("pricey/model"));
    const post = mockFetch.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post?.[0]).toBe("/api/update-config");
    expect(JSON.parse(post?.[1].body)).toEqual({ config_type: "llm", value: "pricey/model" });
  });

  it("filters the model table by search and preselects the current model", async () => {
    render(<ModelSection />);

    expect(await screen.findByLabelText("Select Cheap")).toBeChecked();
    expect(screen.getByText("2 models")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search models"), { target: { value: "pric" } });

    expect(screen.queryByLabelText("Select Cheap")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Select Pricey")).toBeInTheDocument();
    expect(screen.getByText("1 models")).toBeInTheDocument();
  });

  it("applies an edited system prompt", async () => {
    render(<SystemPromptSection />);

    fireEvent.change(await screen.findByDisplayValue("Active {context}"), {
      target: { value: "Rule first. {context}" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply prompt" }));

    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/system-prompt",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ prompt: "Rule first. {context}" }) })
      )
    );
  });

  it("resets the system prompt to the default", async () => {
    render(<SystemPromptSection />);
    await screen.findByDisplayValue("Active {context}");

    fireEvent.click(screen.getByRole("button", { name: "Reset to default" }));

    expect(await screen.findByDisplayValue("Default {context}")).toBeInTheDocument();
  });

  it("shows the backend message when a prompt is refused", async () => {
    mockFetch.mockImplementation(async (url: string, init?: RequestInit) =>
      init?.method === "POST"
        ? ({
            ok: false,
            status: 422,
            json: async () => ({ detail: "The prompt must contain {context}: that is where the documents go." }),
          } as Response)
        : ok(routes[url])
    );
    render(<SystemPromptSection />);

    fireEvent.change(await screen.findByDisplayValue("Active {context}"), { target: { value: "No placeholder" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply prompt" }));

    expect(await screen.findByText(/must contain \{context\}/)).toBeInTheDocument();
  });
});
