import { useState, type FormEvent } from "react";
import {
  answersUrl,
  reportUrl,
  RUN_NAME_PATTERN,
  useCurrentRun,
  useRedteamRuns,
  type AttackSet,
  type RedteamJob,
  type RedteamRun,
  type RedteamRuns,
} from "../services/redteam";
// The page reuses the look of the Controls page: card, title, buttons, table and badges.
import "../styles/security-page.css";
import "../styles/redteam-page.css";

// "11 Nov, 11:26": short enough to stay on one line.
const formatDate = (createdAt: number) =>
  new Date(createdAt).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

// "meta-llama/llama-3.3-70b-instruct" -> the model name in bold, its provider small underneath.
function ChatModel({ model }: Readonly<{ model?: string }>) {
  if (!model) return <span className="redteam-muted">unknown</span>;
  const [provider, name] = model.includes("/") ? model.split("/", 2) : ["", model];
  return (
    <div title={model}>
      <div className="lt-strong">{name}</div>
      {provider && <div className="lt-id">{provider}</div>}
    </div>
  );
}

// "off", "llm", "nlp" or "llm+nlp" as badges; the NLP badge shows its threshold.
function Defenses({ settings }: Readonly<{ settings: Record<string, string> }>) {
  const defenses = settings.defenses;
  if (!defenses) return <span className="redteam-muted">unknown</span>;
  if (defenses === "off") return <span className="defense-badge defense-badge--off">Off</span>;
  return (
    <div className="redteam-badges">
      {defenses.split("+").map((defense) => (
        <span key={defense} className="defense-badge defense-badge--ready">
          {defense === "nlp" && settings.nlp_threshold ? `NLP ${settings.nlp_threshold}` : defense.toUpperCase()}
        </span>
      ))}
    </div>
  );
}

// Red when attacks got through, green when none did; orange when answers could not be judged,
// because then the share is not reliable.
const scoreTone = (run: RedteamRun) => {
  if (run.errors > 0) return "redteam-score--incomplete";
  return run.got_through === 0 ? "redteam-score--none" : "redteam-score--some";
};

// The share of attacks that got through, with a small bar. A run that is still going has no score yet.
function GotThrough({ run, running }: Readonly<{ run: RedteamRun; running: boolean }>) {
  if (running) return <span className="redteam-muted">running...</span>;
  const percent = run.attacks > 0 ? Math.round((run.got_through / run.attacks) * 100) : 0;
  const tone = scoreTone(run);
  return (
    <div className={`redteam-score ${tone}`}>
      <div className="redteam-score__value">{percent}%</div>
      <div className="redteam-score__bar" aria-hidden="true">
        <span style={{ width: `${percent}%` }} />
      </div>
      <div className="lt-id">
        {run.got_through} of {run.attacks}
        {run.errors > 0 && `, ${run.errors} errors: incomplete`}
      </div>
    </div>
  );
}

function RunRow({ run, promptfooUrl, running }: Readonly<{ run: RedteamRun; promptfooUrl: string; running: boolean }>) {
  return (
    <tr className="lt-tr">
      <td className="lt-td">
        <div className="lt-strong redteam-nowrap">{run.name}</div>
        <div className="lt-id redteam-nowrap">
          {formatDate(run.created_at)} · {run.attack_set ? `${run.attack_set} set` : "unknown set"}
        </div>
      </td>
      <td className="lt-td">
        <ChatModel model={run.settings.llm} />
      </td>
      <td className="lt-td">
        <Defenses settings={run.settings} />
      </td>
      <td className="lt-td">{run.settings.prompt ?? <span className="redteam-muted">unknown</span>}</td>
      <td className="lt-td">
        <GotThrough run={run} running={running} />
      </td>
      <td className="lt-td">
        <div className="redteam-links">
          <a href={reportUrl(promptfooUrl, run.id)} target="_blank" rel="noopener noreferrer">
            Report
          </a>
          <a href={answersUrl(promptfooUrl, run.id)} target="_blank" rel="noopener noreferrer">
            Answers
          </a>
        </div>
      </td>
    </tr>
  );
}

// runningId: the run the page started that is still going, if any.
function RunsTable({ result, runningId }: Readonly<{ result: RedteamRuns; runningId: string | null }>) {
  if (result.runs.length === 0) {
    return (
      <p className="redteam-muted">
        No runs yet. Start one above, for example named <code>baseline</code>, with the default settings.
      </p>
    );
  }
  return (
    <div className="lt-table-wrap redteam-table-wrap">
      <table className="lt-table redteam-table">
        <thead>
          <tr>
            <th className="lt-th">Run</th>
            <th className="lt-th">Chat model</th>
            <th className="lt-th">Defenses</th>
            <th className="lt-th" title="System prompt">Prompt</th>
            <th className="lt-th">Got through</th>
            <th className="lt-th">In promptfoo</th>
          </tr>
        </thead>
        <tbody>
          {result.runs.map((run) => (
            <RunRow key={run.id} run={run} promptfooUrl={result.promptfooUrl} running={run.id === runningId} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Quick checks a change; the workshop set is the one to compare settings with.
const ATTACK_SETS: { value: AttackSet; label: string }[] = [
  { value: "quick", label: "Quick check: 12 attacks, about a minute" },
  { value: "workshop", label: "Workshop: 72 attacks, about 7 minutes" },
  { value: "full", label: "Full: 216 attacks, 45-60 minutes" },
];

// Name and attack set, then Start. The backend refuses (with the reason) a used name,
// a defense that is not Active yet, or a second run while one is going.
function StartRunForm({ running, onStart }: Readonly<{ running: boolean; onStart: (name: string, attackSet: AttackSet) => Promise<void> }>) {
  const [name, setName] = useState("");
  const [attackSet, setAttackSet] = useState<AttackSet>("workshop");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const runName = name.trim();
    if (!RUN_NAME_PATTERN.test(runName)) {
      setError("Start the run name with a letter or digit; then use letters, digits, '.', '_' and '-', at most 64.");
      return;
    }
    setStarting(true);
    setError("");
    try {
      await onStart(runName, attackSet);
      setName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  };

  return (
    <form className="redteam-start" onSubmit={handleSubmit}>
      <label className="redteam-field">
        <span>Run name</span>
        <input
          className="controls-input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="what you changed, e.g. nlp-defense"
          maxLength={64}
        />
      </label>
      <label className="redteam-field">
        <span>Attack set</span>
        <select className="controls-input" value={attackSet} onChange={(event) => setAttackSet(event.target.value as AttackSet)}>
          {ATTACK_SETS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" className="security-apply__btn" disabled={running || starting || name.trim() === ""}>
        {starting ? "Starting..." : "Start run"}
      </button>
      {error && (
        <p className="security-error redteam-start__error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

// How far the run started from this page is.
function RunProgress({ job }: Readonly<{ job: RedteamJob }>) {
  if (job.status === "error") {
    return <p className="security-error">Run '{job.name}' stopped: {job.error}</p>;
  }
  if (job.status === "complete") {
    return <p className="redteam-progress__done">Run '{job.name}' is done; it is at the top of the list below.</p>;
  }
  const percent = job.total > 0 ? Math.round((job.progress / job.total) * 100) : 0;
  return (
    <div className="redteam-progress" role="status">
      <div className="redteam-progress__label">
        <strong>Run '{job.name}' is going</strong>
        <span>{job.total > 0 ? `${job.progress} of ${job.total} attacks` : "Loading the attack set..."}</span>
      </div>
      <progress max={100} value={percent} aria-label={`Run ${job.name}: ${percent}%`} />
    </div>
  );
}

function RedTeamPage() {
  const { result, error, reload } = useRedteamRuns();
  const { job, start } = useCurrentRun(reload);
  const runningId = job?.status === "running" ? job.run_id : null;

  return (
    <div className="security-page redteam-page">
      <section className="security-box" aria-label="Automated red teaming">
        <h1 className="security-title">Automated red teaming</h1>
        <p className="security-subtitle">
          A run sends the same set of attacks to LLASER with promptfoo and counts how many get through. Change one
          setting on the Controls page, start a run, and compare. A run uses some OpenRouter credit.
        </p>

        <section className="security-group">
          <h2 className="security-group__title">Start a run</h2>
          <StartRunForm running={job?.status === "running"} onStart={start} />
          {job && <RunProgress job={job} />}
        </section>

        <section className="security-group">
          <header className="redteam-header">
            <h2 className="security-group__title redteam-header__title">Runs</h2>
            <div className="redteam-actions">
              <button type="button" className="security-apply__btn security-apply__btn--secondary" onClick={reload}>
                Refresh
              </button>
              {result && (
                <a
                  className="security-apply__btn security-apply__btn--secondary redteam-link-button"
                  href={result.promptfooUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open promptfoo
                </a>
              )}
            </div>
          </header>

          {error && (
            <p className="security-error" role="alert">
              {error}
            </p>
          )}
          {!result && !error && <p className="security-loading">Loading runs...</p>}
          {result && <RunsTable result={result} runningId={runningId} />}
        </section>
      </section>
    </div>
  );
}

export default RedTeamPage;
