import { useEffect, useState } from "react";

const POLL_MS = 5000;

// Alerts that still wait for Accept or Deny on the Alerts page.
export const fetchPendingAlertCount = async (): Promise<number> => {
  const response = await fetch("/api/prompt-alerts");
  if (!response.ok) throw new Error(`Failed to load alerts (${response.status})`);
  const data = (await response.json()) as { alerts?: { status?: string }[] };
  return (data.alerts ?? []).filter((alert) => alert.status === "pending").length;
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
