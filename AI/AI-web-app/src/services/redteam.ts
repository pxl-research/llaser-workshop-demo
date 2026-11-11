import { useCallback, useEffect, useRef, useState } from "react";

// The promptfoo red-team runs, as the backend passes them on (GET /api/redteam/runs).

export interface RedteamRun {
  id: string;
  name: string;
  // Milliseconds since 1970.
  created_at: number;
  // "quick", "workshop" or "full"; null for runs started by hand.
  attack_set: string | null;
  // LLASER's settings during the run, e.g. { llm: "...", defenses: "nlp" }.
  settings: Record<string, string>;
  attacks: number;
  got_through: number;
  errors: number;
}

export interface RedteamRuns {
  runs: RedteamRun[];
  // Where the browser opens the promptfoo UI, e.g. http://127.0.0.1:3002.
  promptfooUrl: string;
}

// The promptfoo UI runs on its own port of the host LLASER is opened on:
// nginx only lets localhost and 127.0.0.1 through, so the host name must stay the same.
const promptfooUiUrl = (port: number) => `${window.location.protocol}//${window.location.hostname}:${port}`;

// Links into the promptfoo UI for one run.
export const reportUrl = (promptfooUrl: string, runId: string) =>
  `${promptfooUrl}/reports?evalId=${encodeURIComponent(runId)}`;
export const answersUrl = (promptfooUrl: string, runId: string) =>
  `${promptfooUrl}/eval/${encodeURIComponent(runId)}`;

// The backend's error message ("promptfoo is not running. Start it with ..."), or the HTTP status.
const errorMessage = async (response: Response, failed: string): Promise<string> => {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Not JSON: fall back to the status below.
  }
  return `${failed} (HTTP ${response.status})`;
};

export const fetchRedteamRuns = async (): Promise<RedteamRuns> => {
  const response = await fetch("/api/redteam/runs");
  if (!response.ok) throw new Error(await errorMessage(response, "Loading the runs failed"));
  const data = (await response.json()) as { runs: RedteamRun[]; promptfoo_ui_port: number };
  return { runs: data.runs, promptfooUrl: promptfooUiUrl(data.promptfoo_ui_port) };
};

// A run in progress keeps adding results; reload now and then while the page is open.
const REFRESH_MS = 15000;

interface RedteamRunsState {
  result: RedteamRuns | null;
  // Empty when the last load worked; the last result stays visible next to an error.
  error: string;
}

// Loads the runs when the page opens and every 15 seconds; reload() loads them right away.
export const useRedteamRuns = () => {
  const [state, setState] = useState<RedteamRunsState>({ result: null, error: "" });

  const reload = useCallback(() => {
    fetchRedteamRuns()
      .then((result) => setState({ result, error: "" }))
      .catch((error: unknown) => {
        const message = error instanceof Error ? error.message : String(error);
        setState((previous) => ({ ...previous, error: message }));
      });
  }, []);

  useEffect(() => {
    reload();
    const timer = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  return { ...state, reload };
};

// --- Starting a run from the page ---

export type AttackSet = "quick" | "workshop" | "full";

// The run started from the page, while promptfoo runs it and after.
export interface RedteamJob {
  name: string;
  attack_set: AttackSet;
  status: "running" | "complete" | "error";
  // Attacks done so far, of total; total is 0 until promptfoo has loaded the attack set.
  progress: number;
  total: number;
  run_id: string | null;
  error: string | null;
}

// Run names as ./005_promptfoo_run.sh accepts them, a letter or digit first; the backend checks the same.
export const RUN_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

export const startRedteamRun = async (name: string, attackSet: AttackSet): Promise<RedteamJob> => {
  const response = await fetch("/api/redteam/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, attack_set: attackSet }),
  });
  if (!response.ok) throw new Error(await errorMessage(response, "Starting the run failed"));
  return (await response.json()) as RedteamJob;
};

export const fetchCurrentJob = async (): Promise<RedteamJob | null> => {
  const response = await fetch("/api/redteam/runs/current");
  if (!response.ok) throw new Error(await errorMessage(response, "Loading the current run failed"));
  return ((await response.json()) as { job: RedteamJob | null }).job;
};

// How often the page asks how far a running run is.
const JOB_POLL_MS = 2000;

// The run started from the page: checked when the page opens, then every 2 seconds while it runs.
// onFinished is called once when a run stops, so the page can reload the run list.
export const useCurrentRun = (onFinished: () => void) => {
  const [job, setJob] = useState<RedteamJob | null>(null);
  const running = job?.status === "running";

  const check = useCallback(() => {
    fetchCurrentJob()
      .then(setJob)
      .catch(() => {}); // keep showing the last state; the run list shows when promptfoo is down
  }, []);

  useEffect(() => {
    check();
  }, [check]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(check, JOB_POLL_MS);
    return () => window.clearInterval(timer);
  }, [running, check]);

  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) onFinished();
    wasRunning.current = running;
  }, [running, onFinished]);

  // Throws with the backend's reason when the run cannot start (name taken, defense not active, ...).
  const start = async (name: string, attackSet: AttackSet) => {
    setJob(await startRedteamRun(name, attackSet));
  };

  return { job, start };
};
