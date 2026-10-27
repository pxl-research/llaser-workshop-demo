import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchSecurityConfig,
  updateSecurityConfig,
  type DefenseStatus,
  type SecurityConfig,
} from "../services/security";
import "../styles/security-page.css";

function StatusBadge({ status, error }: { status: DefenseStatus; error?: string | null }) {
  const labels: Record<DefenseStatus, string> = {
    off: "Off",
    loading: "Loading…",
    ready: "Active",
    error: "Unavailable",
  };

  return (
    <span
      className={`defense-badge defense-badge--${status}`}
      title={status === "error" && error ? error : undefined}
    >
      {status === "loading" && <span className="defense-badge__spinner" />}
      {labels[status]}
    </span>
  );
}

function SecurityPage() {
  const [config, setConfig] = useState<SecurityConfig | null>(null);
  const [staged, setStaged] = useState<{ homebrew: boolean; nlp: boolean }>({
    homebrew: false,
    nlp: false,
  });
  const [error, setError] = useState<string | null>(null);
  const [isApplying, setIsApplying] = useState(false);
  const pollRef = useRef<number | null>(null);

  const isLoading =
    config?.homebrew_status === "loading" || config?.nlp_defense_status === "loading";

  const loadConfig = useCallback(async () => {
    try {
      const data = await fetchSecurityConfig();
      setConfig(data);
      setStaged({ homebrew: data.use_homebrew, nlp: data.use_nlp_defense });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load security config");
    }
  }, []);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  useEffect(() => {
    if (isLoading) {
      pollRef.current = window.setInterval(() => void loadConfig(), 2000);
    } else if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [isLoading, loadConfig]);

  const hasPendingChanges =
    config !== null &&
    (staged.homebrew !== config.use_homebrew || staged.nlp !== config.use_nlp_defense);

  const handleApply = async () => {
    if (!hasPendingChanges || isApplying) return;
    setIsApplying(true);
    setError(null);
    try {
      const updated = await updateSecurityConfig({
        use_homebrew: staged.homebrew,
        use_nlp_defense: staged.nlp,
      });
      setConfig(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to apply security config");
    } finally {
      setIsApplying(false);
    }
  };

  const handleThresholdChange = async (value: number) => {
    setError(null);
    try {
      const updated = await updateSecurityConfig({ nlp_confidence_threshold: value });
      setConfig(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update threshold");
    }
  };

  if (!config) {
    return (
      <div className="security-page">
        <div className="security-box">
          {error ? (
            <p className="security-error">{error}</p>
          ) : (
            <p className="security-loading">Loading security configuration…</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="security-page">
      <div className="security-box">
        <h1 className="security-title">Security Controls</h1>
        <p className="security-subtitle">
          Toggle prompt defenses. Changes require applying. Some defenses need a local model
          before they become active.
        </p>

        {error && <p className="security-error">{error}</p>}
        {config.nlp_defense_status === "error" && config.nlp_defense_error && (
          <p className="security-error">{config.nlp_defense_error}</p>
        )}
        {config.homebrew_status === "error" && config.homebrew_error && (
          <p className="security-error">{config.homebrew_error}</p>
        )}

        <section className="security-group">
          <h2 className="security-group__title">Prompt Defenses</h2>

          <div className="defense-row">
            <label className="security-toggle">
              <input
                type="checkbox"
                checked={staged.homebrew}
                disabled={isLoading || isApplying}
                onChange={(e) => setStaged((s) => ({ ...s, homebrew: e.target.checked }))}
              />
              <span className="security-toggle__label">LLM-based defense (Homebrew)</span>
              <span className="security-toggle__desc">
                Uses a Qwen LLM on the DGX Spark to classify prompts as safe or malicious.
              </span>
            </label>
            <StatusBadge status={config.homebrew_status} error={config.homebrew_error} />
          </div>

          <div className="defense-row">
            <label className="security-toggle">
              <input
                type="checkbox"
                checked={staged.nlp}
                disabled={isLoading || isApplying}
                onChange={(e) => setStaged((s) => ({ ...s, nlp: e.target.checked }))}
              />
              <span className="security-toggle__label">NLP/ML defense (DistilBERT classifier)</span>
              <span className="security-toggle__desc">
                Runs on this laptop. Needs the model files in{" "}
                <code>models/malicious_prompt_detector</code> (see the README).
              </span>
            </label>
            <StatusBadge status={config.nlp_defense_status} error={config.nlp_defense_error} />
          </div>

          {hasPendingChanges && (
            <div className="security-apply">
              <button
                className="security-apply__btn"
                onClick={() => void handleApply()}
                disabled={isApplying || isLoading}
              >
                {isApplying ? "Applying…" : "Apply changes"}
              </button>
              <button
                className="security-apply__btn security-apply__btn--secondary"
                onClick={() => setStaged({ homebrew: config.use_homebrew, nlp: config.use_nlp_defense })}
                disabled={isApplying || isLoading}
              >
                Reset
              </button>
            </div>
          )}

          <div className="security-slider">
            <label className="security-slider__label">
              NLP confidence threshold: <strong>{config.nlp_confidence_threshold.toFixed(2)}</strong>
            </label>
            <input
              type="range"
              min="0.1"
              max="0.99"
              step="0.01"
              value={config.nlp_confidence_threshold}
              disabled={config.nlp_defense_status !== "ready"}
              onChange={(e) => void handleThresholdChange(parseFloat(e.target.value))}
            />
            <span className="security-slider__hint">
              Lower = more sensitive (more false positives). Higher = less sensitive (may miss attacks).
            </span>
          </div>
        </section>
      </div>
    </div>
  );
}

export default SecurityPage;
