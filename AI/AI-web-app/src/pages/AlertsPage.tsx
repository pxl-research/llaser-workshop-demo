import { useEffect, useState } from "react";
import "../styles/alerts-page.css";

interface MaliciousPromptAlert {
  id: string;
  prompt: string;
  timestamp: string;
  riskLevel: "low" | "medium" | "high" | "critical";
  threatTypes: string[];
  sessionID?: string;
  status: "pending" | "accepted" | "denied";
}

function AlertsPage() {
  const [alerts, setAlerts] = useState<MaliciousPromptAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"all" | "pending" | "accepted" | "denied">("pending");

  useEffect(() => {
    fetchAlerts();
    const interval = window.setInterval(fetchAlerts, 10000);
    return () => window.clearInterval(interval);
  }, []);

  const fetchAlerts = async () => {
    try {
      setLoading(true);
      const response = await fetch("/api/prompt-alerts");
      if (response.ok) {
        const data = await response.json();
        setAlerts(data.alerts || []);
        setError("");
      } else {
        setError("Failed to fetch alerts");
      }
    } catch (err) {
      setError(`Error fetching alerts: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setLoading(false);
    }
  };

  const handleAlertAction = async (
    alertId: string,
    action: "accept" | "deny"
  ) => {
    try {
      const response = await fetch(`/api/prompt-alerts/${alertId}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action }),
      });

      if (response.ok) {
        setAlerts((prev) =>
          prev.map((alert) =>
            alert.id === alertId
              ? {
                  ...alert,
                  status: action === "accept" ? "accepted" : "denied",
                }
              : alert
          )
        );
      } else {
        setError("Failed to process alert action");
      }
    } catch (err) {
      setError(`Error processing action: ${err instanceof Error ? err.message : "Unknown error"}`);
    }
  };

  const filteredAlerts =
    filter === "all" ? alerts : alerts.filter((alert) => alert.status === filter);

  const getRiskLevelColor = (level: string): string => {
    switch (level) {
      case "critical":
        return "#dc2626";
      case "high":
        return "#ea580c";
      case "medium":
        return "#eab308";
      case "low":
        return "#22c55e";
      default:
        return "#6b7280";
    }
  };

  const getRiskLevelBgColor = (level: string): string => {
    switch (level) {
      case "critical":
        return "#fee2e2";
      case "high":
        return "#feed7d";
      case "medium":
        return "#fef3c7";
      case "low":
        return "#dcfce7";
      default:
        return "#f3f4f6";
    }
  };

  return (
    <div className="alerts-page" style={{ margin: "24px"}}>
      <div className="alerts-header">
        <h1>Malicious Prompt Alerts</h1>
        <button className="refresh-btn" onClick={fetchAlerts} disabled={loading}>
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
          {(["all", "pending", "accepted", "denied"] as const).map((status) => (
            <button
              key={status}
              className={`filter-btn ${filter === status ? "active" : ""}`}
              onClick={() => setFilter(status)}
            >
              {status.charAt(0).toUpperCase() + status.slice(1)}
              {status === "all"
                ? ` (${alerts.length})`
                : ` (${alerts.filter((a) => a.status === status).length})`}
            </button>
          ))}
        </div>
      </div>

      {loading && !alerts.length ? (
        <div className="loading-message">Loading alerts...</div>
      ) : filteredAlerts.length === 0 ? (
        <div className="empty-message">
          No {filter === "all" ? "" : filter} alerts found.
        </div>
      ) : (
        <div className="alerts-container">
          {filteredAlerts.map((alert) => (
            <div key={alert.id} className="alert-card">
              <div className="alert-header-row">
                <div className="alert-title-section">
                  <h3 className="alert-title">Suspicious Prompt Detected</h3>
                  <span
                    className="risk-badge"
                    style={{
                      backgroundColor: getRiskLevelBgColor(alert.riskLevel),
                      color: getRiskLevelColor(alert.riskLevel),
                    }}
                  >
                    {alert.riskLevel.toUpperCase()}
                  </span>
                </div>
                <span className="alert-timestamp">{new Date(alert.timestamp).toLocaleString()}</span>
              </div>

              <div className="alert-details">
                <div className="detail-row">
                  <strong>Prompt:</strong>
                  <p className="prompt-text">{alert.prompt}</p>
                </div>

                {alert.threatTypes.length > 0 && (
                  <div className="detail-row">
                    <strong>Threat Types:</strong>
                    <div className="threat-tags">
                      {alert.threatTypes.map((threat, idx) => (
                        <span key={idx} className="threat-tag">
                          {threat}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {alert.sessionID && (
                  <div className="detail-row">
                    <strong>Session ID:</strong>
                    <span className="session-id">{alert.sessionID}</span>
                  </div>
                )}

                <div className="detail-row">
                  <strong>Status:</strong>
                  <span className={`status-badge status-${alert.status}`}>
                    {alert.status.charAt(0).toUpperCase() + alert.status.slice(1)}
                  </span>
                </div>
              </div>

              {alert.status === "pending" && (
                <div className="alert-actions">
                  <button
                    className="btn-accept"
                    onClick={() => handleAlertAction(alert.id, "accept")}
                  >
                    Accept
                  </button>
                  <button
                    className="btn-deny"
                    onClick={() => handleAlertAction(alert.id, "deny")}
                  >
                    Deny
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default AlertsPage;
