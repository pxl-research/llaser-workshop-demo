import { useCallback, useEffect, useState } from "react";
import { isRedTeamAlert } from "../services/alerts";
import { getSessionId } from "../services/ChatService";
import "../styles/alerts-page.css";

type AlertStatus = "pending" | "accepted" | "denied";
type Filter = "all" | AlertStatus;

interface MaliciousPromptAlert {
  id: string;
  prompt: string;
  timestamp: string;
  threatTypes: string[];
  sessionID?: string;
  status: AlertStatus;
  defense?: "llm" | "nlp";
  score?: number | null;
}

const FILTERS: Filter[] = ["all", "pending", "accepted", "denied"];

const capitalize = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1);

// Where the blocked question came from, in words an attendee recognises.
const askedIn = (alert: MaliciousPromptAlert): string => {
  if (isRedTeamAlert(alert)) return "a red-team run";
  if (alert.sessionID === getSessionId()) return "this tab";
  return "another tab";
};

const fetchAlertList = async (): Promise<{ alerts?: MaliciousPromptAlert[]; error?: string }> => {
  try {
    const response = await fetch("/api/prompt-alerts");
    if (!response.ok) return { error: "Failed to fetch alerts" };
    const data = await response.json();
    return { alerts: data.alerts || [] };
  } catch (err) {
    return { error: `Error fetching alerts: ${err instanceof Error ? err.message : "Unknown error"}` };
  }
};

const defenseLabel = (alert: MaliciousPromptAlert): string => {
  if (alert.defense === "llm") return "LLM defense";
  if (alert.defense !== "nlp") return "Blocked question";
  return typeof alert.score === "number" ? `NLP defense, score ${alert.score.toFixed(2)}` : "NLP defense";
};

interface AlertCardProps {
  alert: MaliciousPromptAlert;
  onAction: (alertId: string, action: "accept" | "deny") => void;
}

function AlertCard({ alert, onAction }: Readonly<AlertCardProps>) {
  return (
    <div className="alert-card">
      <div className="alert-header-row">
        <h3 className="alert-title">{defenseLabel(alert)}</h3>
        <span className="alert-timestamp">{new Date(alert.timestamp).toLocaleString()}</span>
      </div>

      <div className="alert-details">
        <div className="detail-row">
          <strong>Prompt:</strong>
          <p className="prompt-text">{alert.prompt}</p>
        </div>

        {/* The LLM defense's reason is model output: plain text only, never Markdown. */}
        {alert.defense === "llm" && alert.threatTypes.length > 0 && (
          <div className="detail-row">
            <strong>Reason:</strong>
            <p className="reason-text">{alert.threatTypes.join(" ")}</p>
          </div>
        )}

        {alert.defense !== "llm" && alert.threatTypes.length > 0 && (
          <div className="detail-row">
            <strong>Threat Types:</strong>
            <div className="threat-tags">
              {alert.threatTypes.map((threat) => (
                <span key={threat} className="threat-tag">
                  {threat}
                </span>
              ))}
            </div>
          </div>
        )}

        {alert.sessionID && (
          <div className="detail-row">
            <strong>Asked in:</strong>
            <span>{askedIn(alert)}</span>
          </div>
        )}

        <div className="detail-row">
          <strong>Status:</strong>
          <span className={`status-badge status-${alert.status}`}>{capitalize(alert.status)}</span>
        </div>
      </div>

      {alert.status === "pending" && (
        <div className="alert-actions">
          <button className="btn-accept" onClick={() => onAction(alert.id, "accept")}>
            Accept
          </button>
          <button className="btn-deny" onClick={() => onAction(alert.id, "deny")}>
            Deny
          </button>
        </div>
      )}
    </div>
  );
}

function AlertsPage() {
  const [alerts, setAlerts] = useState<MaliciousPromptAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("pending");
  const [showRedTeam, setShowRedTeam] = useState(false);

  // Only the first load and a Refresh click show Loading; the background poll stays quiet.
  const fetchAlerts = useCallback(
    () =>
      fetchAlertList().then((result) => {
        if (result.alerts) setAlerts(result.alerts);
        setError(result.error ?? "");
        setLoading(false);
      }),
    []
  );

  useEffect(() => {
    void fetchAlerts();
    const interval = window.setInterval(() => void fetchAlerts(), 10000);
    return () => window.clearInterval(interval);
  }, [fetchAlerts]);

  const refresh = () => {
    setLoading(true);
    void fetchAlerts();
  };

  const handleAlertAction = async (alertId: string, action: "accept" | "deny") => {
    try {
      const response = await fetch(`/api/prompt-alerts/${alertId}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action }),
      });

      if (response.ok) {
        const status: AlertStatus = action === "accept" ? "accepted" : "denied";
        setAlerts((prev) => prev.map((alert) => (alert.id === alertId ? { ...alert, status } : alert)));
      } else {
        setError("Failed to process alert action");
      }
    } catch (err) {
      setError(`Error processing action: ${err instanceof Error ? err.message : "Unknown error"}`);
    }
  };

  const redTeamCount = alerts.filter(isRedTeamAlert).length;
  const visibleAlerts = showRedTeam ? alerts : alerts.filter((alert) => !isRedTeamAlert(alert));
  const countFor = (status: Filter) =>
    status === "all" ? visibleAlerts.length : visibleAlerts.filter((a) => a.status === status).length;
  const filteredAlerts = filter === "all" ? visibleAlerts : visibleAlerts.filter((alert) => alert.status === filter);

  const renderAlerts = () => {
    if (loading && !alerts.length) return <div className="loading-message">Loading alerts...</div>;
    if (filteredAlerts.length === 0) {
      return <div className="empty-message">No {filter === "all" ? "" : filter} alerts found.</div>;
    }
    return (
      <div className="alerts-container">
        {filteredAlerts.map((alert) => (
          <AlertCard key={alert.id} alert={alert} onAction={handleAlertAction} />
        ))}
      </div>
    );
  };

  return (
    <div className="alerts-page" style={{ margin: "24px" }}>
      <div className="alerts-header">
        <div>
          <h1>Alerts</h1>
          <p className="alerts-subtitle">
            A defense blocked these questions. Accept: the chat model answers, in the chat that asked. Deny: the
            question is dropped. Both unblock that chat.
          </p>
        </div>
        <button className="refresh-btn" onClick={refresh} disabled={loading}>
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="error-message">
          <strong>Error:</strong> {error}
        </div>
      )}

      <div className="filter-section">
        <div className="filter-buttons">
          {FILTERS.map((status) => (
            <button
              key={status}
              className={`filter-btn ${filter === status ? "active" : ""}`}
              onClick={() => setFilter(status)}
            >
              {capitalize(status)} ({countFor(status)})
            </button>
          ))}
        </div>
        <label className="redteam-toggle">
          <input type="checkbox" checked={showRedTeam} onChange={(e) => setShowRedTeam(e.target.checked)} />
          Show red-team run alerts ({redTeamCount})
        </label>
      </div>

      {renderAlerts()}
    </div>
  );
}

export default AlertsPage;
