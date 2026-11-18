import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ModelSection, SystemPromptSection } from "../pages/ControlSections";

const mockFetch = vi.fn();
const ok = (body: unknown) => ({ ok: true, json: async () => body }) as Response;

const routes: Record<string, unknown> = {
  "/api/system-prompt": { prompt: "Active {context}", default_prompt: "Default {context}" },
  "/api/llm": { llm: "cheap/model" },
  "/api/available-llms": [
    { id: "pricey/model", name: "Pricey", prompt_price: "0.000003", completion_price: "0.000015" },
    { id: "cheap/model", name: "Cheap", prompt_price: "0.0000001", completion_price: "0.0000003" },
    { id: "openai/gpt-4o-mini", name: "GPT-4o mini", prompt_price: "0.00000015", completion_price: "0.0000006" },
    { id: "mistralai/mistral-nemo", name: "Nemo", prompt_price: "0.00000003", completion_price: "0.00000003" },
  ],
};

function serve(url: string, init?: RequestInit) {
  if (init?.method !== "POST") return ok(routes[url]);
  if (url === "/api/system-prompt") {
    const prompt = JSON.parse(String(init.body)).prompt ?? "Default {context}";
    return ok({ prompt, default_prompt: "Default {context}" });
  }
  return ok(JSON.parse(String(init.body)));
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

  it("switches the model with a POST to /api/llm", async () => {
    render(<ModelSection />);
    await waitFor(() => expect(screen.getByText(/Current:/).textContent).toContain("($0.10"));

    fireEvent.click(screen.getByRole("button", { name: "Show all 4 models" }));
    fireEvent.click(screen.getByLabelText("Select Pricey"));
    fireEvent.click(screen.getByRole("button", { name: "Use this model" }));

    await waitFor(() => expect(screen.getByText(/Current:/).textContent).toContain("pricey/model"));
    const post = mockFetch.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post?.[0]).toBe("/api/llm");
    expect(JSON.parse(post?.[1].body)).toEqual({ llm: "pricey/model" });
  });

  it("filters the model table by search and preselects the current model", async () => {
    render(<ModelSection />);

    expect(await screen.findByLabelText("Select Cheap")).toBeChecked();
    fireEvent.click(await screen.findByRole("button", { name: "Show all 4 models" }));
    expect(screen.getByText("4 models")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search models"), { target: { value: "pric" } });

    expect(screen.queryByLabelText("Select Cheap")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Select Pricey")).toBeInTheDocument();
    expect(screen.getByText("1 models")).toBeInTheDocument();
  });

  it("shows the workshop picks and the current model by default", async () => {
    render(<ModelSection />);

    expect(await screen.findByLabelText("Select GPT-4o mini")).toBeInTheDocument();
    expect(screen.getByLabelText("Select Nemo")).toBeInTheDocument();
    expect(screen.getByLabelText("Select Cheap")).toBeChecked();
    expect(screen.queryByLabelText("Select Pricey")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Search models")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next page" })).not.toBeInTheDocument();
  });

  it("switches between all models and the workshop picks", async () => {
    render(<ModelSection />);

    fireEvent.click(await screen.findByRole("button", { name: "Show all 4 models" }));
    expect(screen.getByLabelText("Select Pricey")).toBeInTheDocument();
    expect(screen.getByLabelText("Search models")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show workshop picks" }));
    expect(screen.queryByLabelText("Select Pricey")).not.toBeInTheDocument();
  });

  it("selects a model with a radio button or a click on its row", async () => {
    render(<ModelSection />);

    const nemo = await screen.findByLabelText("Select Nemo");
    expect(nemo).toHaveAttribute("type", "radio");
    expect(nemo).toHaveAttribute("name", "chat-model");

    fireEvent.click(screen.getByText("mistralai/mistral-nemo"));
    expect(nemo).toBeChecked();
    expect(screen.getByLabelText("Select Cheap")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Use this model" })).toBeEnabled();
  });

  it("says the edited prompt is not applied yet, until Apply", async () => {
    render(<SystemPromptSection />);

    const box = await screen.findByDisplayValue("Active {context}");
    expect(screen.queryByText("Not applied yet")).not.toBeInTheDocument();
    fireEvent.change(box, { target: { value: "Rule first. {context}" } });
    expect(screen.getByText("Not applied yet")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Apply prompt" }));
    await waitFor(() => expect(screen.queryByText("Not applied yet")).not.toBeInTheDocument());
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
