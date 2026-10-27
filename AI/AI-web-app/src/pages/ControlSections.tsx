import { useEffect, useState } from "react";
import {
  fetchCurrentModel,
  fetchModels,
  fetchSystemPrompt,
  pricePerMillion,
  updateModel,
  updateSystemPrompt,
  type LlmModel,
} from "../services/controls";

const errorText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

const priceLabel = (m: LlmModel) =>
  `${pricePerMillion(m.prompt_price)} in / ${pricePerMillion(m.completion_price)} out per 1M tokens`;

export function ModelSection() {
  const [models, setModels] = useState<LlmModel[]>([]);
  const [current, setCurrent] = useState("");
  const [choice, setChoice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchCurrentModel()
      .then(setCurrent)
      .catch((e) => setError(errorText(e, "Failed to load the current model")));
    fetchModels()
      .then(setModels)
      .catch((e) => setError(errorText(e, "Failed to load the model list")));
  }, []);

  const currentModel = models.find((m) => m.id === current);

  const apply = async () => {
    setBusy(true);
    setError(null);
    try {
      await updateModel(choice);
      setCurrent(choice);
      setChoice("");
    } catch (e) {
      setError(errorText(e, "Failed to switch the model"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="security-group">
      <h2 className="security-group__title">Chat Model</h2>
      <p className="security-subtitle">
        Current: <code>{current || "…"}</code>
        {currentModel && ` (${priceLabel(currentModel)})`}. A restart of the app returns to the model
        in <code>.env</code>.
      </p>
      {error && <p className="security-error">{error}</p>}
      <div className="security-apply">
        <input
          className="controls-input"
          list="llm-models"
          aria-label="Chat model"
          placeholder="Search a model, for example openai/gpt-4o-mini"
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
        />
        <datalist id="llm-models">
          {models.map((m) => (
            <option key={m.id} value={m.id}>{`${m.name} · ${priceLabel(m)}`}</option>
          ))}
        </datalist>
        <button
          className="security-apply__btn"
          onClick={() => void apply()}
          disabled={busy || !models.some((m) => m.id === choice)}
        >
          {busy ? "Switching…" : "Use this model"}
        </button>
      </div>
    </section>
  );
}

export function SystemPromptSection() {
  const [active, setActive] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const show = (prompt: string) => {
    setActive(prompt);
    setDraft(prompt);
  };

  useEffect(() => {
    fetchSystemPrompt()
      .then((p) => show(p.prompt))
      .catch((e) => setError(errorText(e, "Failed to load the system prompt")));
  }, []);

  const send = async (prompt: string | null) => {
    setBusy(true);
    setError(null);
    try {
      show((await updateSystemPrompt(prompt)).prompt);
    } catch (e) {
      setError(errorText(e, "Failed to apply the system prompt"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="security-group">
      <h2 className="security-group__title">System Prompt</h2>
      <p className="security-subtitle">
        <code>{"{context}"}</code> is where the retrieved documents go. Try the rules before or after
        it. A restart of the app returns to the default.
      </p>
      {error && <p className="security-error">{error}</p>}
      <textarea
        className="controls-input controls-prompt"
        aria-label="System prompt"
        rows={14}
        value={draft}
        disabled={active === null || busy}
        onChange={(e) => setDraft(e.target.value)}
      />
      <div className="security-apply">
        <button
          className="security-apply__btn"
          onClick={() => void send(draft)}
          disabled={busy || draft === active}
        >
          Apply prompt
        </button>
        <button
          className="security-apply__btn security-apply__btn--secondary"
          onClick={() => void send(null)}
          disabled={busy}
        >
          Reset to default
        </button>
      </div>
    </section>
  );
}
