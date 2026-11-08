import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent, FormEvent, KeyboardEvent } from "react";
import { fetchAcceptedAnswer, fetchAlertStatus, sendMessageToAPI, type AlertStatus } from "../services/ChatService";
import { deleteDocument, listDocuments, uploadDocument } from "../services/DocumentService";
import { fetchSecurityConfig, type DefenseStatus } from "../services/security";
import { useSystemReadiness } from "../components/SystemReadinessContext";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import sendIconSrc from "../assets/up-arrow.png";
import { createLoadingMessage, scrollParentToBottom } from "./chatUtils";
import "../styles/chat-page.css";

interface Message {
  text: string;
  sender: "user" | "response";
  upload?: { percent: number; startedAt: number };
}

// How often the chat checks the review of its blocked question.
const ALERT_POLL_MS = 2000;

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

const REVIEW_MESSAGES = {
  pending: "⏳ Waiting for review. Accept or deny this question on the **Alerts** page.",
  accepted: "✓ A reviewer accepted your question.\n\n",
  denied: "✗ A reviewer denied this question. You can ask something else.",
  gone: "The alert no longer exists (the app restarted). Ask your question again.",
};

// ponytail: fixed guess, Azure layout took ~20s for both a 10 and a 36 page PDF; tune if uploads run long or short.
const PROCESSING_ESTIMATE_SECONDS = 20;

const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

const uploadLabel = (percent: number, elapsed: number) =>
  percent < 100
    ? `Uploading ${percent}%`
    : `Reading and indexing · ${clock(elapsed)} of about ${clock(PROCESSING_ESTIMATE_SECONDS)}`;

// Capped at 95% so the bar never looks finished before the server answers.
const uploadValue = (percent: number, elapsed: number) =>
  percent < 100 ? percent : Math.min(95, Math.round((elapsed / PROCESSING_ESTIMATE_SECONDS) * 100));

function ResponseBody({ msg, now }: Readonly<{ msg: Message; now: number }>) {
  if (msg.upload) {
    const elapsed = (now - msg.upload.startedAt) / 1000;
    return (
      <div className="upload-progress">
        <span>
          {msg.text}: {uploadLabel(msg.upload.percent, elapsed)}
        </span>
        <progress max={100} value={uploadValue(msg.upload.percent, elapsed)} aria-label={`Uploading ${msg.text}`} />
      </div>
    );
  }
  if (msg.text === "") {
    return (
      <output className="typing-dots" aria-label="LLASER is typing">
        <span />
        <span />
        <span />
      </output>
    );
  }
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>;
}

function ChatPage() {
  const [message, setMessage] = useState<string>("");
  const [chat, setChat] = useState<Message[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [documents, setDocuments] = useState<string[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  // The alert of this chat's blocked question; accepted means its answer can be fetched.
  const [blockedAlertId, setBlockedAlertId] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [defenses, setDefenses] = useState<{ homebrew: DefenseStatus; nlp: DefenseStatus }>({
    homebrew: "off",
    nlp: "off",
  });
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const hasMessages = chat.length > 0;
  const { isReady, statusMessage } = useSystemReadiness();

  const loadDefenseStatus = useCallback(() => {
    fetchSecurityConfig()
      .then((cfg) => setDefenses({ homebrew: cfg.homebrew_status, nlp: cfg.nlp_defense_status }))
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadDefenseStatus();
    const id = window.setInterval(loadDefenseStatus, 10000);
    return () => window.clearInterval(id);
  }, [loadDefenseStatus]);
  const loadDocuments = useCallback(() => {
    listDocuments().then(setDocuments).catch(() => {});
  }, []);

  useEffect(() => {
    if (isReady) loadDocuments();
  }, [isReady, loadDocuments]);
  // Ticks the elapsed time in the upload bubble.
  useEffect(() => {
    if (!isUploading) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [isUploading]);

  const canInteract = isReady && !isUploading && !isDeleting;
  // Uploads and new questions wait for the answer: both append to the chat the stream is writing into.
  // A blocked question waits for review: its answer may still arrive.
  const canSend = canInteract && !isStreaming && !blockedAlertId;
  const readyPlaceholder = blockedAlertId
    ? "Waiting for review on the Alerts page..."
    : "what would you like to know?";
  const inputPlaceholder = isReady ? readyPlaceholder : "Chat will be available when the AI system is ready...";
  
  useEffect(() => {
    scrollParentToBottom(chatEndRef.current);
  }, [chat]);

  const addResponse = useCallback((text: string) => {
    setChat((prev) => [...prev, { text, sender: "response" }]);
  }, []);

  // Adds an answer bubble with typing dots and returns a function that appends text to it.
  const startAnswerBubble = useCallback((firstText = "") => {
    setChat((prev) => [...prev, createLoadingMessage()]);
    let answer = firstText;
    return (delta: string) => {
      answer += delta;
      const text = answer;
      setChat((prev) => [...prev.slice(0, -1), { text, sender: "response" }]);
    };
  }, []);

  // A blocked question waits for review on the Alerts page.
  // Every few seconds: ask the backend for the review. Accepted: show the answer. Denied or gone: say so.
  useEffect(() => {
    if (!blockedAlertId) return;
    let stopped = false; // set when this chat stops waiting, e.g. the page closes

    const waitForReview = async () => {
      let status: AlertStatus = "pending";
      while (status === "pending") {
        await sleep(ALERT_POLL_MS);
        if (stopped) return;
        status = await fetchAlertStatus(blockedAlertId).catch(() => "pending" as const); // retry on errors
        if (stopped) return;
      }

      setBlockedAlertId(null);
      if (status === "accepted") {
        setIsStreaming(true);
        await fetchAcceptedAnswer(blockedAlertId, startAnswerBubble(REVIEW_MESSAGES.accepted));
        setIsStreaming(false);
      } else {
        addResponse(REVIEW_MESSAGES[status]);
      }
    };

    void waitForReview();
    return () => {
      stopped = true;
    };
  }, [blockedAlertId, addResponse, startAnswerBubble]);

  const handleSend = async () => {
    if (!canSend || message.trim() === "") return;

    setChat((prev) => [...prev, { text: message, sender: "user" }]);
    setMessage("");

    setIsStreaming(true);
    const { alertId } = await sendMessageToAPI(message, startAnswerBubble());
    setIsStreaming(false);

    if (alertId) {
      setBlockedAlertId(alertId);
      addResponse(REVIEW_MESSAGES.pending);
    }
  };

  const handlePickFiles = () => {
    if (!canSend) return;
    fileInputRef.current?.click();
  };

  const handleFilesSelected = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0 || !canSend) return;

    setIsUploading(true);
    // Each file gets its own bubble; the last message is always that bubble, since sending is blocked meanwhile.
    const showLast = (msg: Message) => setChat((prev) => [...prev.slice(0, -1), msg]);
    try {
      for (const file of Array.from(fileList)) {
        const startedAt = Date.now();
        setNow(startedAt);
        setChat((prev) => [...prev, { text: file.name, sender: "response", upload: { percent: 0, startedAt } }]);
        try {
          const result = await uploadDocument(file, (percent) =>
            showLast({ text: file.name, sender: "response", upload: { percent, startedAt } })
          );
          showLast({ text: `✓ ${result.message}`, sender: "response" });
        } catch (error) {
          const detail = error instanceof Error ? error.message : String(error);
          showLast({ text: `✗ Upload failed: ${file.name}: ${detail}`, sender: "response" });
        }
      }
    } finally {
      setIsUploading(false);
      loadDocuments();
    }
  };

  const handleDelete = async (name: string) => {
    if (!canSend || !window.confirm(`Delete ${name}? LLASER will no longer use it to answer.`)) return;

    setIsDeleting(true);
    try {
      const result = await deleteDocument(name);
      setChat((prev) => [...prev, { text: `✓ ${result.message}`, sender: "response" }]);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setChat((prev) => [...prev, { text: `✗ Delete failed: ${name}: ${detail}`, sender: "response" }]);
    } finally {
      setIsDeleting(false);
      loadDocuments();
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    handleSend();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <section className="chat-page" aria-label="AI chat workspace">
      <div className="chat-shell">
        {!hasMessages && (
          <div className="chat-empty-state">
            <p className="chat-eyebrow">LLASER assistant</p>
            <h2>Ask LLASER about the uploaded documents.</h2>
            <p className="chat-empty-copy">
              {isReady
                ? "Start with a short question about the uploaded documents."
                : statusMessage}
            </p>
            <div className="chat-suggestions" aria-label="Example prompts">
              {[
                "Who teaches Applied Secure AI?",
                "When is the exam and how long does it take?",
                "When is the project deadline?",
              ].map((suggestion) => (
                <button
                  className="suggestion-chip"
                  key={suggestion}
                  type="button"
                  onClick={() => setMessage(suggestion)}
                  disabled={!canInteract}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className={`chat-card ${hasMessages ? "chat-card--active" : ""}`}>
          {documents.length > 0 && (
            <details className="chat-documents">
              <summary>Documents ({documents.length})</summary>
              <ul>
                {documents.map((name) => (
                  <li key={name}>
                    <span>{name}</span>
                    <button
                      aria-label={`Delete ${name}`}
                      className="chat-document-delete"
                      disabled={!canSend}
                      type="button"
                      onClick={() => void handleDelete(name)}
                      title={canSend ? "Delete document" : "Wait until LLASER is done"}
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <div className="chat-scroll-area">
            {chat.map((msg, index) => (
              <div
                key={index}
                className={`message-row message-row--${msg.sender}`}
              >
                {msg.sender === "response" ? (
                  <div className="assistant-message">
                    <div className="message-bubble message-bubble--response">
                      <ResponseBody msg={msg} now={now} />
                    </div>
                  </div>
                ) : (
                  <div className="message-bubble message-bubble--user">{msg.text}</div>
                )}
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>

          <div className="chat-defense-bar">
            {defenses.homebrew === "off" && defenses.nlp === "off" ? (
              <span className="chat-defense-badge chat-defense-badge--off">No prompt defenses active</span>
            ) : (
              <>
                {defenses.homebrew !== "off" && (
                  <span className={`chat-defense-badge chat-defense-badge--${defenses.homebrew}`}>
                    LLM Defense: {defenses.homebrew === "ready" ? "active" : defenses.homebrew}
                  </span>
                )}
                {defenses.nlp !== "off" && (
                  <span className={`chat-defense-badge chat-defense-badge--${defenses.nlp}`}>
                    NLP Defense: {defenses.nlp === "ready" ? "active" : defenses.nlp}
                  </span>
                )}
              </>
            )}
          </div>

          <form className="chat-input-bar" onSubmit={handleSubmit}>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf"
              className="chat-file-input"
              multiple
              onChange={(e) => {
                void handleFilesSelected(e.target.files);
                e.target.value = "";
              }}
            />
            <button
              aria-label="Attach document"
              className="chat-attach-button"
              disabled={!canSend}
              type="button"
              onClick={handlePickFiles}
              title={canSend ? "Attach document(s)" : "Wait for the AI system to be ready"}
            >
              📎
            </button>
            <input
              aria-label="what would you like to know?"
              type="text"
              placeholder={inputPlaceholder}
              value={message}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              className="chat-input"
              disabled={!canInteract}
            />
            <button
              aria-label="Send message"
              className="chat-send-button"
              disabled={!canSend || message.trim() === ""}
              type="submit"
            >
              <img src={sendIconSrc} alt="" aria-hidden="true" className="chat-send-icon" />
            </button>
          </form>
        </div>
      </div>
    </section>
  );
}

export default ChatPage;
