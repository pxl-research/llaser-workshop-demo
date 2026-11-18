import { useEffect, useState } from "react";

const POLL_MS = 5000;

// promptfoo red-team runs use session ids that start with this prefix (promptfoo/redteam.yaml).
export const isRedTeamAlert = (alert: { sessionID?: string }): boolean =>
  (alert.sessionID ?? "").startsWith("promptfoo-redteam-");

// Alerts that still wait for Accept or Deny on the Alerts page; red-team run alerts do not count.
export const fetchPendingAlertCount = async (): Promise<number> => {
  const response = await fetch("/api/prompt-alerts");
  if (!response.ok) throw new Error(`Failed to load alerts (${response.status})`);
  const data = (await response.json()) as { alerts?: { status?: string; sessionID?: string }[] };
  return (data.alerts ?? []).filter((alert) => alert.status === "pending" && !isRedTeamAlert(alert)).length;
};

// Polls the pending alert count; keeps the last count while the backend is unreachable.
export const usePendingAlertCount = (): number => {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let active = true;
    const load = () => {
      fetchPendingAlertCount()
        .then((next) => {
          if (active) setCount(next);
        })
        .catch(() => {});
    };
    load();
    const id = window.setInterval(load, POLL_MS);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, []);

  return count;
};
