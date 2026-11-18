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

const PAGE_SIZE = 25;

// The models README.md compares ("Models to compare").
const WORKSHOP_MODELS = [
  "meta-llama/llama-3.3-70b-instruct",
  "openai/gpt-6-luna",
  "openai/gpt-4o-mini",
  "mistralai/mistral-nemo",
];

const compact = (n?: number | null) => {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${Math.round(n / 1_000_000)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
};

interface ModelTableProps {
  rows: LlmModel[];
  choice: string;
  onChoose: (id: string) => void;
}

// A click anywhere on a row selects it: every cell is a label of the row's radio button.
function ModelTable({ rows, choice, onChoose }: Readonly<ModelTableProps>) {
  return (
    <div className="lt-table-wrap">
      <table className="lt-table">
        <colgroup>
          <col style={{ width: "8%" }} />
          <col style={{ width: "44%" }} />
          <col style={{ width: "16%" }} />
          <col style={{ width: "16%" }} />
          <col style={{ width: "16%" }} />
        </colgroup>
        <thead>
          <tr>
            <th className="lt-th"></th>
            <th className="lt-th">Name</th>
            <th className="lt-th">Context</th>
            <th className="lt-th">Input /1M</th>
            <th className="lt-th">Output /1M</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => {
            const inputId = `chat-model-${m.id}`;
            return (
              <tr key={m.id} className="lt-tr">
                <td className="lt-td lt-center">
                  <input
                    id={inputId}
                    type="radio"
                    name="chat-model"
                    checked={m.id === choice}
                    onChange={() => onChoose(m.id)}
                    aria-label={`Select ${m.name}`}
                  />
                </td>
                <td className="lt-td">
                  <label htmlFor={inputId} className="lt-row-label">
                    <div className="lt-strong">{m.name}</div>
                    <div className="lt-id">{m.id}</div>
                  </label>
                </td>
                <td className="lt-td lt-num">
                  <label htmlFor={inputId} className="lt-row-label">
                    {compact(m.context_length)}
                  </label>
                </td>
                <td className="lt-td lt-num">
                  <label htmlFor={inputId} className="lt-row-label">
                    {pricePerMillion(m.prompt_price)}
                  </label>
                </td>
                <td className="lt-td lt-num">
                  <label htmlFor={inputId} className="lt-row-label">
                    {pricePerMillion(m.completion_price)}
                  </label>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface PagerProps {
  page: number;
  totalPages: number;
  onPage: (page: number) => void;
}

function Pager({ page, totalPages, onPage }: Readonly<PagerProps>) {
  return (
    <div className="lt-pager">
      <button className="lt-icon-btn" onClick={() => onPage(1)} disabled={page === 1} aria-label="First page">
        «
      </button>
      <button className="lt-icon-btn" onClick={() => onPage(page - 1)} disabled={page === 1} aria-label="Previous page">
        ‹
      </button>
      <span>
        Page {page} / {totalPages}
      </span>
      <button
        className="lt-icon-btn"
        onClick={() => onPage(page + 1)}
        disabled={page === totalPages}
        aria-label="Next page"
      >
        ›
      </button>
      <button
        className="lt-icon-btn"
        onClick={() => onPage(totalPages)}
        disabled={page === totalPages}
        aria-label="Last page"
      >
        »
      </button>
    </div>
  );
}

export function ModelSection() {
  const [models, setModels] = useState<LlmModel[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [current, setCurrent] = useState("");
  const [choice, setChoice] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchCurrentModel()
      .then((id) => {
        setCurrent(id);
        setChoice(id);
      })
      .catch((e) => setError(errorText(e, "Failed to load the current model")));
    fetchModels()
      .then(setModels)
      .catch((e) => setError(errorText(e, "Failed to load the model list")));
  }, []);

  const currentModel = models.find((m) => m.id === current);
  const picks = models.filter((m) => WORKSHOP_MODELS.includes(m.id) || m.id === current);
  const query = search.trim().toLowerCase();
  const rows = models.filter((m) => `${m.name} ${m.id}`.toLowerCase().includes(query));
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pageRows = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const onSearch = (value: string) => {
    setSearch(value);
    setPage(1);
  };

  const apply = async () => {
    setBusy(true);
    setError(null);
    try {
      await updateModel(choice);
      setCurrent(choice);
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
      <div className="lt-topbar">
        {showAll && (
          <input
            className="lt-search"
            aria-label="Search models"
            placeholder="Search by name"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && onSearch("")}
          />
        )}
        <button
          className="security-apply__btn"
          onClick={() => void apply()}
          disabled={busy || !choice || choice === current}
        >
          {busy ? "Switching…" : "Use this model"}
        </button>
      </div>
      <ModelTable rows={showAll ? pageRows : picks} choice={choice} onChoose={setChoice} />
      <div className="lt-footer">
        {showAll ? (
          <>
            <span>{rows.length.toLocaleString()} models</span>
            <button className="lt-link-btn" onClick={() => setShowAll(false)}>
              Show workshop picks
            </button>
            <Pager page={page} totalPages={totalPages} onPage={setPage} />
          </>
        ) : (
          <button className="lt-link-btn" onClick={() => setShowAll(true)}>
            Show all {models.length.toLocaleString()} models
          </button>
        )}
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
        {active !== null && draft !== active && <span className="controls-pending">Not applied yet</span>}
      </div>
    </section>
  );
}
