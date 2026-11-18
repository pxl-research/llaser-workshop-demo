import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  fetchSecurityConfig,
  updateSecurityConfig,
  type DefenseStatus,
  type SecurityConfig,
} from "../services/security";
import { ModelSection, SystemPromptSection } from "./ControlSections";
import "../styles/security-page.css";

function StatusBadge({
  status,
  error,
  fallback = false,
}: {
  status: DefenseStatus;
  error?: string | null;
  fallback?: boolean;
}) {
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
      {status === "ready" && fallback && " (OpenRouter fallback)"}
    </span>
  );
}

interface DefenseRowProps {
  label: string;
  description: ReactNode;
  checked: boolean;
  status: DefenseStatus;
  error?: string | null;
  fallback?: boolean;
  onToggle: (on: boolean) => void;
}

// One switch with its status badge; its error shows right under it.
function DefenseRow({ label, description, checked, status, error, fallback, onToggle }: Readonly<DefenseRowProps>) {
  return (
    <div className="defense-item">
      <div className="defense-row">
        <label className="security-toggle">
          <input
            type="checkbox"
            checked={checked}
            disabled={status === "loading"}
            onChange={(e) => onToggle(e.target.checked)}
          />
          <span className="security-toggle__label">{label}</span>
          <span className="security-toggle__desc">{description}</span>
        </label>
        <StatusBadge status={status} error={error} fallback={fallback} />
      </div>
      {status === "error" && error && <p className="security-error">{error}</p>}
    </div>
  );
}

function SecurityPage() {
  const [config, setConfig] = useState<SecurityConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const isLoading =
    config?.homebrew_status === "loading" || config?.nlp_defense_status === "loading";

  const loadConfig = useCallback(
    () =>
      fetchSecurityConfig()
        .then(setConfig)
        .catch((e) => setError(e instanceof Error ? e.message : "Failed to load security config")),
    []
  );

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  // While a defense loads, poll until it is Active or Unavailable.
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

  // Every setting applies at once.
  const applyNow = async (update: Partial<SecurityConfig>, failure: string) => {
    setError(null);
    try {
      setConfig(await updateSecurityConfig(update));
    } catch (e) {
      setError(e instanceof Error ? e.message : failure);
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

  const thresholdUsable = config.nlp_defense_status === "ready";

  return (
    <div className="security-page">
      <div className="security-box">
        <h1 className="security-title">Controls</h1>
        <p className="security-subtitle">Every change applies at once and lasts until the app restarts.</p>

        {error && <p className="security-error">{error}</p>}

        <section className="security-group">
          <h2 className="security-group__title">Prompt Defenses</h2>

          <DefenseRow
            label="LLM defense"
            description="A Qwen model on the PXL DGX Spark labels each question safe or malicious. If the Spark is unreachable, a Qwen model on OpenRouter takes over."
            checked={config.use_homebrew}
            status={config.homebrew_status}
            error={config.homebrew_error}
            fallback={config.homebrew_backend === "openrouter"}
            onToggle={(on) => void applyNow({ use_homebrew: on }, "Failed to switch the LLM defense")}
          />

          <DefenseRow
            label="NLP defense"
            description={`A small classifier (DistilBERT) on this laptop gives each question a score from 0 to 1. Model ${
              config.nlp_model_version ?? "not loaded"
            }.`}
            checked={config.use_nlp_defense}
            status={config.nlp_defense_status}
            error={config.nlp_defense_error}
            onToggle={(on) => void applyNow({ use_nlp_defense: on }, "Failed to switch the NLP defense")}
          />

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
              disabled={!thresholdUsable}
              onChange={(e) =>
                void applyNow(
                  { nlp_confidence_threshold: Number.parseFloat(e.target.value) },
                  "Failed to update threshold"
                )
              }
            />
            <span className="security-slider__hint">
              {thresholdUsable
                ? "A question is blocked when its NLP score is at or above this value. Lower: blocks more, also harmless questions. Higher: lets more attacks through."
                : "Switch on the NLP defense to use the threshold."}
            </span>
          </div>
        </section>

        <SystemPromptSection />
        <ModelSection />

        <section className="security-group">
          <h2 className="security-group__title">Answer Rendering</h2>

          <div className="defense-row">
            <label className="security-toggle">
              <input
                type="checkbox"
                checked={config.safe_answer_rendering}
                onChange={(e) =>
                  void applyNow({ safe_answer_rendering: e.target.checked }, "Failed to change answer rendering")
                }
              />
              <span className="security-toggle__label">Safe answer rendering</span>
              <span className="security-toggle__desc">
                Treats LLASER's answers as untrusted: images in an answer are not loaded (their address
                could carry data to another server) and links open in a new tab, with their site shown.
                Applies at once.
              </span>
            </label>
            <StatusBadge status={config.safe_answer_rendering ? "ready" : "off"} />
          </div>
        </section>
      </div>
    </div>
  );
}

export default SecurityPage;
