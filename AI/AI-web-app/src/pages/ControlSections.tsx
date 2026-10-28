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

const compact = (n?: number | null) => {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${Math.round(n / 1_000_000)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
};

export function ModelSection() {
  const [models, setModels] = useState<LlmModel[]>([]);
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
        <input
          className="lt-search"
          aria-label="Search models"
          placeholder="Search by name"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && onSearch("")}
        />
        <button
          className="security-apply__btn"
          onClick={() => void apply()}
          disabled={busy || !choice || choice === current}
        >
          {busy ? "Switching…" : "Use this model"}
        </button>
      </div>
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
            {pageRows.map((m) => {
              const selected = m.id === choice;
              return (
                <tr key={m.id} className="lt-tr">
                  <td className="lt-td lt-center">
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => setChoice(selected ? "" : m.id)}
                      aria-label={`Select ${m.name}`}
                    />
                  </td>
                  <td className="lt-td">
                    <div className="lt-strong">{m.name}</div>
                    <div className="lt-id">{m.id}</div>
                  </td>
                  <td className="lt-td lt-num">{compact(m.context_length)}</td>
                  <td className="lt-td lt-num">{pricePerMillion(m.prompt_price)}</td>
                  <td className="lt-td lt-num">{pricePerMillion(m.completion_price)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="lt-footer">
        <span>{rows.length.toLocaleString()} models</span>
        <div className="lt-pager">
          <button className="lt-icon-btn" onClick={() => setPage(1)} disabled={page === 1} aria-label="First page">
            «
          </button>
          <button className="lt-icon-btn" onClick={() => setPage(page - 1)} disabled={page === 1} aria-label="Previous page">
            ‹
          </button>
          <span>
            Page {page} / {totalPages}
          </span>
          <button
            className="lt-icon-btn"
            onClick={() => setPage(page + 1)}
            disabled={page === totalPages}
            aria-label="Next page"
          >
            ›
          </button>
          <button
            className="lt-icon-btn"
            onClick={() => setPage(totalPages)}
            disabled={page === totalPages}
            aria-label="Last page"
          >
            »
          </button>
        </div>
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
