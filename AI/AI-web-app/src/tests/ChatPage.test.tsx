import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
  act,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import ChatPage from "../pages/ChatPage";
import { createLoadingMessage, scrollParentToBottom } from "../pages/chatUtils";
import { sendMessageToAPI } from "../services/ChatService";
import {
  deleteDocument,
  listDocuments,
  uploadDocument,
  type UploadDocumentResult,
} from "../services/DocumentService";

vi.mock("../services/ChatService", () => ({
  sendMessageToAPI: vi.fn(),
}));

vi.mock("../services/DocumentService", () => ({
  uploadDocument: vi.fn(),
  listDocuments: vi.fn(),
  deleteDocument: vi.fn(),
}));

vi.mock("../components/SystemReadinessContext", () => ({
  useSystemReadiness: () => ({
    readiness: { status: "ready", components: {} },
    isReady: true,
    isError: false,
    isLoading: false,
    statusMessage: "AI system is ready.",
    refresh: vi.fn(),
  }),
}));

const mockedSendMessageToAPI = vi.mocked(sendMessageToAPI);
const mockedUploadDocument = vi.mocked(uploadDocument);
const mockedListDocuments = vi.mocked(listDocuments);
const mockedDeleteDocument = vi.mocked(deleteDocument);
const pickFiles = (...names: string[]) => {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: names.map((name) => new File(["x"], name, { type: "application/pdf" })) } });
};
const asInput = (el: HTMLElement) => el as HTMLInputElement;
const answerWith = (...pieces: string[]) =>
  mockedSendMessageToAPI.mockImplementation(async (_question, onDelta) => {
    await Promise.resolve();
    pieces.forEach((piece) => onDelta(piece));
  });

describe("ChatPage Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedListDocuments.mockReset().mockResolvedValue([]);
    cleanup();
  });

  it("renders correctly", () => {
    render(<ChatPage />);

    const inputs = screen.getAllByPlaceholderText("what would you like to know?");
    const attachButton = screen.getByRole("button", { name: "Attach document" });
    const sendButton = screen.getByRole("button", { name: "Send message" });

    expect(inputs[0]).toBeInTheDocument();
    expect(attachButton).toBeInTheDocument();
    expect(sendButton).toBeInTheDocument();
  });

  it("adds a user message when sending via button", async () => {
    answerWith("Mocked ", "answer");

    render(<ChatPage />);

    const input = screen.getAllByPlaceholderText("what would you like to know?")[0];
    const sendButton = screen.getByRole("button", { name: "Send message" });

    fireEvent.change(input, { target: { value: "Hello AI" } });
    fireEvent.click(sendButton);

    expect(screen.getByText("Hello AI")).toBeInTheDocument();
    expect(asInput(input).value).toBe("");

    expect(screen.getByRole("status", { name: "LLASER is typing" })).toBeInTheDocument();
    expect(await screen.findByText("Mocked answer")).toBeInTheDocument();
  });

  it("adds a user message when pressing Enter", async () => {
    answerWith("Enter answer");

    render(<ChatPage />);

    const input = screen.getAllByPlaceholderText("what would you like to know?")[0];

    fireEvent.change(input, { target: { value: "Hello via Enter" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", charCode: 13 });

    expect(screen.getByText("Hello via Enter")).toBeInTheDocument();
    expect(asInput(input).value).toBe("");

    expect(screen.getByRole("status", { name: "LLASER is typing" })).toBeInTheDocument();
    expect(await screen.findByText("Enter answer")).toBeInTheDocument();
  });

  it("does not send empty messages", () => {
    answerWith("Should not be used");

    render(<ChatPage />);

    const sendButton = screen.getByRole("button", { name: "Send message" });

    fireEvent.click(sendButton);

    expect(mockedSendMessageToAPI).not.toHaveBeenCalled();
    expect(screen.queryByRole("status", { name: "LLASER is typing" })).not.toBeInTheDocument();
  });

  it("displays the API response after the loading message", async () => {
    answerWith("Final answer");

    render(<ChatPage />);

    const input = screen.getAllByPlaceholderText("what would you like to know?")[0];
    const sendButton = screen.getByRole("button", { name: "Send message" });

    fireEvent.change(input, { target: { value: "Test response delay" } });
    fireEvent.click(sendButton);

    expect(screen.getByText("Test response delay")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "LLASER is typing" })).toBeInTheDocument();

    expect(await screen.findByText("Final answer")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("status", { name: "LLASER is typing" })).not.toBeInTheDocument()
    );
  });

  it("clears the input field after sending a message", async () => {
    answerWith("Some answer");

    render(<ChatPage />);

    const input = screen.getAllByPlaceholderText("what would you like to know?")[0];
    const sendButton = screen.getByRole("button", { name: "Send message" });

    fireEvent.change(input, { target: { value: "Message to send" } });
    expect(asInput(input).value).toBe("Message to send");

    fireEvent.click(sendButton);

    expect(asInput(input).value).toBe("");

    expect(screen.getByRole("status", { name: "LLASER is typing" })).toBeInTheDocument();
    expect(await screen.findByText("Some answer")).toBeInTheDocument();
    expect(asInput(input).value).toBe("");
  });

  it("scrolls chat container to bottom when chat changes", async () => {
    answerWith("Scroll test answer");

    const scrollToSpy = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      value: scrollToSpy,
      writable: true,
    });

    render(<ChatPage />);

    const input = screen.getAllByPlaceholderText("what would you like to know?")[0];
    const sendButton = screen.getByRole("button", { name: "Send message" });

    fireEvent.change(input, { target: { value: "Trigger scroll" } });
    fireEvent.click(sendButton);

    expect(await screen.findByText("Trigger scroll")).toBeInTheDocument();
    expect(scrollToSpy).toHaveBeenCalled();
  });

  it("file picker offers only PDF documents", () => {
    render(<ChatPage />);

    const input = document.querySelector("input[type=\"file\"]") as HTMLInputElement;
    expect(input.accept).toBe(".pdf");
  });

  it("shows the answer while it streams and blocks sending until it is done", async () => {
    let finish = () => {};
    mockedSendMessageToAPI.mockImplementation(async (_question, onDelta) => {
      await Promise.resolve();
      onDelta("Partial");
      await new Promise<void>((resolve) => {
        finish = () => {
          onDelta(" answer");
          resolve();
        };
      });
    });

    render(<ChatPage />);

    const input = screen.getAllByPlaceholderText("what would you like to know?")[0];
    const sendButton = screen.getByRole("button", { name: "Send message" });

    fireEvent.change(input, { target: { value: "Stream please" } });
    fireEvent.click(sendButton);

    expect(await screen.findByText("Partial")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "LLASER is typing" })).not.toBeInTheDocument();

    fireEvent.change(input, { target: { value: "Second question" } });
    expect(sendButton).toBeDisabled();

    finish();

    expect(await screen.findByText("Partial answer")).toBeInTheDocument();
    await waitFor(() => expect(sendButton).toBeEnabled());
    expect(mockedSendMessageToAPI).toHaveBeenCalledTimes(1);
  });

  it("shows the upload percentage while the file is sent", async () => {
    mockedUploadDocument.mockImplementation((_file, onUploadProgress) => {
      onUploadProgress(45);
      return new Promise(() => {});
    });

    render(<ChatPage />);
    pickFiles("doc.pdf");

    expect(await screen.findByText("doc.pdf: Uploading 45%")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Uploading doc.pdf" })).toHaveAttribute("value", "45");
    expect(screen.getByRole("button", { name: "Attach document" })).toBeDisabled();
  });

  it("then shows elapsed time against the estimate, capped at 95%, then the result", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    let finish!: (result: UploadDocumentResult) => void;
    mockedUploadDocument.mockImplementation((_file, onUploadProgress) => {
      onUploadProgress(100);
      return new Promise((resolve) => {
        finish = resolve;
      });
    });

    try {
      render(<ChatPage />);
      pickFiles("doc.pdf");
      expect(await screen.findByText("doc.pdf: Reading and indexing · 0:00 of about 0:20")).toBeInTheDocument();

      act(() => vi.advanceTimersByTime(10_000));
      expect(screen.getByText("doc.pdf: Reading and indexing · 0:10 of about 0:20")).toBeInTheDocument();
      expect(screen.getByRole("progressbar")).toHaveAttribute("value", "50");

      act(() => vi.advanceTimersByTime(55_000));
      expect(screen.getByText("doc.pdf: Reading and indexing · 1:05 of about 0:20")).toBeInTheDocument();
      expect(screen.getByRole("progressbar")).toHaveAttribute("value", "95");

      finish({ message: "Uploaded and indexed doc.pdf (12 chunks)." });

      expect(await screen.findByText("✓ Uploaded and indexed doc.pdf (12 chunks).")).toBeInTheDocument();
      expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("gives each file its own result and keeps going after a failure", async () => {
    mockedUploadDocument
      .mockRejectedValueOnce(new Error("Document processing failed."))
      .mockResolvedValueOnce({ message: "Uploaded and indexed b.pdf (3 chunks)." });

    render(<ChatPage />);
    pickFiles("a.pdf", "b.pdf");

    expect(await screen.findByText("✓ Uploaded and indexed b.pdf (3 chunks).")).toBeInTheDocument();
    expect(screen.getByText("✗ Upload failed: a.pdf: Document processing failed.")).toBeInTheDocument();
    expect(mockedUploadDocument).toHaveBeenCalledTimes(2);
  });

  it("refreshes the document list after an upload", async () => {
    mockedListDocuments.mockResolvedValueOnce([]).mockResolvedValueOnce(["doc.pdf"]);
    mockedUploadDocument.mockResolvedValueOnce({ message: "Uploaded and indexed doc.pdf (3 chunks)." });

    render(<ChatPage />);
    await waitFor(() => expect(mockedListDocuments).toHaveBeenCalledTimes(1));
    pickFiles("doc.pdf");

    expect(await screen.findByRole("button", { name: "Delete doc.pdf" })).toBeInTheDocument();
    expect(screen.getByText("Documents (1)")).toBeInTheDocument();
  });

  it("deletes a document after confirmation and refreshes the list", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    mockedListDocuments.mockResolvedValueOnce(["a.pdf", "b.pdf"]).mockResolvedValueOnce(["b.pdf"]);
    mockedDeleteDocument.mockResolvedValueOnce({ message: "Deleted a.pdf." });

    try {
      render(<ChatPage />);
      fireEvent.click(await screen.findByRole("button", { name: "Delete a.pdf" }));

      expect(confirm).toHaveBeenCalledWith(expect.stringContaining("a.pdf"));
      expect(await screen.findByText("✓ Deleted a.pdf.")).toBeInTheDocument();
      expect(mockedDeleteDocument).toHaveBeenCalledWith("a.pdf");
      await waitFor(() => expect(screen.queryByRole("button", { name: "Delete a.pdf" })).not.toBeInTheDocument());
      expect(screen.getByRole("button", { name: "Delete b.pdf" })).toBeInTheDocument();
    } finally {
      confirm.mockRestore();
    }
  });

  it("keeps the document when the confirmation is cancelled", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    mockedListDocuments.mockResolvedValueOnce(["a.pdf"]);

    try {
      render(<ChatPage />);
      fireEvent.click(await screen.findByRole("button", { name: "Delete a.pdf" }));

      expect(confirm).toHaveBeenCalled();
      expect(mockedDeleteDocument).not.toHaveBeenCalled();
    } finally {
      confirm.mockRestore();
    }
  });

  it("shows a failed delete in the chat", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    mockedListDocuments.mockResolvedValue(["a.pdf"]);
    mockedDeleteDocument.mockRejectedValueOnce(new Error("Document not found"));

    try {
      render(<ChatPage />);
      fireEvent.click(await screen.findByRole("button", { name: "Delete a.pdf" }));

      expect(await screen.findByText("✗ Delete failed: a.pdf: Document not found")).toBeInTheDocument();
    } finally {
      confirm.mockRestore();
    }
  });
});

// pure helper tests, ensuring coverage of branches and helpers

describe("scrollParentToBottom", () => {
  it("covers null, no-parent, and normal cases", () => {
    const scrollToSpy = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      value: scrollToSpy,
      writable: true,
    });

    scrollParentToBottom(null);

    const orphan = document.createElement("div");
    scrollParentToBottom(orphan);

    const parent = document.createElement("div");
    parent.style.paddingBottom = "10px";
    Object.defineProperty(parent, "scrollHeight", {
      value: 100,
      writable: true,
    });
    const child = document.createElement("div");
    parent.appendChild(child);

    scrollParentToBottom(child);

    expect(scrollToSpy).toHaveBeenCalledWith(
      expect.objectContaining({ top: 90 })
    );
  });
});

describe("createLoadingMessage", () => {
  it("returns the expected loading message", () => {
    expect(createLoadingMessage()).toEqual({
      text: "",
      sender: "response",
    });
  });
});
