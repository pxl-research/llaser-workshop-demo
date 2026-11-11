import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RedTeamPage from "../pages/RedTeamPage";
import type { RedteamJob, RedteamRun } from "../services/redteam";

// The promptfoo UI is on the host the page is opened on (jsdom: localhost).
const PROMPTFOO = `http://${window.location.hostname}:3002`;
const PROMPTFOO_DOWN = "promptfoo is not running. Start it with: docker compose up -d";

// A fake LLASER backend for the three red-team endpoints; tests change its fields.
const backend = {
  runs: [] as RedteamRun[],
  runsDown: false,
  job: null as RedteamJob | null,
  // The answer to POST /api/redteam/runs: a started job, or a refusal.
  start: { status: 200, body: {} as unknown },
};

const answer = (status: number, body: unknown) => ({ ok: status === 200, status, json: async () => body }) as Response;

const mockFetch = vi.fn(async (url: string, init?: RequestInit) => {
  if (url === "/api/redteam/runs" && init?.method === "POST") return answer(backend.start.status, backend.start.body);
  if (url === "/api/redteam/runs") {
    return backend.runsDown ? answer(503, { detail: PROMPTFOO_DOWN }) : answer(200, { runs: backend.runs, promptfoo_ui_port: 3002 });
  }
  if (url === "/api/redteam/runs/current") return answer(200, { job: backend.job });
  throw new Error(`unexpected request ${url}`);
});
vi.stubGlobal("fetch", mockFetch);

const run = (overrides: Partial<RedteamRun> = {}): RedteamRun => ({
  id: "eval-1",
  name: "baseline",
  created_at: Date.UTC(2026, 10, 11, 9, 42),
  attack_set: "workshop",
  settings: { llm: "meta-llama/llama-3.3-70b-instruct", defenses: "off", prompt: "default" },
  attacks: 72,
  got_through: 5,
  errors: 0,
  ...overrides,
});

const job = (overrides: Partial<RedteamJob> = {}): RedteamJob => ({
  name: "nlp-defense",
  attack_set: "workshop",
  status: "running",
  progress: 0,
  total: 72,
  run_id: null,
  error: null,
  ...overrides,
});

const requestsTo = (url: string, method = "GET") =>
  mockFetch.mock.calls.filter(([calledUrl, init]) => calledUrl === url && (init?.method ?? "GET") === method);

const startRun = (name: string, attackSet?: string) => {
  fireEvent.change(screen.getByLabelText("Run name"), { target: { value: name } });
  if (attackSet) fireEvent.change(screen.getByLabelText("Attack set"), { target: { value: attackSet } });
  fireEvent.click(screen.getByRole("button", { name: "Start run" }));
};

describe("Automated red teaming page", () => {
  beforeEach(() => {
    backend.runs = [];
    backend.runsDown = false;
    backend.job = null;
    backend.start = { status: 200, body: job() };
  });

  afterEach(() => {
    cleanup();
    mockFetch.mockClear();
    vi.useRealTimers();
  });

  describe("the run list", () => {
    it("shows each run with its settings and how many attacks got through", async () => {
      backend.runs = [
        run(),
        run({ id: "eval-2", name: "both-defenses", settings: { defenses: "llm+nlp", nlp_threshold: "0.7", prompt: "custom" }, got_through: 0 }),
      ];
      render(<RedTeamPage />);

      const baseline = (await screen.findByText("baseline")).closest("tr")!;
      expect(within(baseline).getByText("llama-3.3-70b-instruct")).toBeInTheDocument();
      expect(within(baseline).getByText("meta-llama")).toBeInTheDocument();
      expect(within(baseline).getByText("Off")).toHaveClass("defense-badge--off");
      expect(within(baseline).getByText("default")).toBeInTheDocument();
      expect(within(baseline).getByText(/workshop set/)).toBeInTheDocument();
      expect(within(baseline).getByText("7%").parentElement).toHaveClass("redteam-score--some");
      expect(within(baseline).getByText("5 of 72")).toBeInTheDocument();

      const defended = screen.getByText("both-defenses").closest("tr")!;
      expect(within(defended).getByText("LLM")).toHaveClass("defense-badge--ready");
      expect(within(defended).getByText("NLP 0.7")).toHaveClass("defense-badge--ready");
      expect(within(defended).getByText("custom")).toBeInTheDocument();
      expect(within(defended).getByText("0%").parentElement).toHaveClass("redteam-score--none");
    });

    it("links each run to its report and answers in promptfoo, in a new tab", async () => {
      backend.runs = [run({ id: "eval-1FH-2026-11-11T09:42:26" })];
      render(<RedTeamPage />);

      const report = await screen.findByRole("link", { name: "Report" });
      expect(report).toHaveAttribute("href", `${PROMPTFOO}/reports?evalId=eval-1FH-2026-11-11T09%3A42%3A26`);
      expect(report).toHaveAttribute("target", "_blank");
      expect(report).toHaveAttribute("rel", "noopener noreferrer");
      expect(screen.getByRole("link", { name: "Answers" })).toHaveAttribute("href", `${PROMPTFOO}/eval/eval-1FH-2026-11-11T09%3A42%3A26`);
      expect(screen.getByRole("link", { name: "Open promptfoo" })).toHaveAttribute("href", PROMPTFOO);
    });

    it("shows errors and unknown values for a run started by hand", async () => {
      backend.runs = [run({ name: "by-hand", attack_set: null, settings: {}, errors: 3 })];
      render(<RedTeamPage />);

      const row = (await screen.findByText("by-hand")).closest("tr")!;
      expect(within(row).getByText(/unknown set/)).toBeInTheDocument();
      // Chat model, defenses and prompt.
      expect(within(row).getAllByText("unknown")).toHaveLength(3);
      expect(within(row).getByText("5 of 72, 3 errors: incomplete")).toBeInTheDocument();
      // Not green or red: with errors the share is not reliable.
      expect(within(row).getByText("7%").parentElement).toHaveClass("redteam-score--incomplete");
    });

    it("shows no score yet for the run that is still going", async () => {
      backend.runs = [run({ id: "eval-9", name: "nlp-defense", attacks: 3, got_through: 0 }), run()];
      backend.job = job({ progress: 3, run_id: "eval-9" });
      render(<RedTeamPage />);

      const going = (await screen.findByText("nlp-defense", { selector: ".lt-strong" })).closest("tr")!;
      expect(await within(going).findByText("running...")).toBeInTheDocument();
      expect(within(going).queryByText("0%")).not.toBeInTheDocument();
      const finished = screen.getByText("baseline").closest("tr")!;
      expect(within(finished).getByText("7%")).toBeInTheDocument();
    });

    it("explains how to start when there are no runs", async () => {
      render(<RedTeamPage />);

      expect(await screen.findByText(/No runs yet/)).toBeInTheDocument();
    });

    it("shows the backend's explanation when promptfoo is not running", async () => {
      backend.runsDown = true;
      render(<RedTeamPage />);

      expect(await screen.findByRole("alert")).toHaveTextContent("docker compose up -d");
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
    });

    it("reloads on Refresh and every 15 seconds, and clears an old error", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      backend.runsDown = true;
      render(<RedTeamPage />);
      await screen.findByRole("alert");

      backend.runsDown = false;
      backend.runs = [run()];
      fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
      expect(await screen.findByText("baseline")).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();

      backend.runs = [run(), run({ id: "eval-2", name: "llm-defense" })];
      await act(() => vi.advanceTimersByTimeAsync(15000));
      expect(await screen.findByText("llm-defense")).toBeInTheDocument();
      expect(requestsTo("/api/redteam/runs")).toHaveLength(3);
    });
  });

  describe("starting a run", () => {
    it("starts a run with its name and attack set and shows its progress", async () => {
      render(<RedTeamPage />);
      await screen.findByText(/No runs yet/);
      // The workshop set is the default: it is the one to compare settings with.
      expect(screen.getByLabelText("Attack set")).toHaveValue("workshop");

      startRun("nlp-defense", "quick");

      expect(await screen.findByRole("status")).toHaveTextContent("Run 'nlp-defense' is going");
      expect(screen.getByRole("status")).toHaveTextContent("0 of 72 attacks");
      const [, init] = requestsTo("/api/redteam/runs", "POST")[0];
      expect(JSON.parse(String(init?.body))).toEqual({ name: "nlp-defense", attack_set: "quick" });
      expect(screen.getByLabelText("Run name")).toHaveValue("");
      expect(screen.getByRole("button", { name: "Start run" })).toBeDisabled();
    });

    it("shows why the backend refuses a run", async () => {
      backend.start = { status: 409, body: { detail: "There already is a run named 'baseline'. Choose a name that says what you changed." } };
      render(<RedTeamPage />);
      await screen.findByText(/No runs yet/);

      startRun("baseline");

      expect(await screen.findByRole("alert")).toHaveTextContent("There already is a run named 'baseline'");
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
      expect(screen.getByLabelText("Run name")).toHaveValue("baseline");
    });

    it("checks the name before asking the backend", async () => {
      render(<RedTeamPage />);
      await screen.findByText(/No runs yet/);

      startRun("my run!");

      expect(await screen.findByRole("alert")).toHaveTextContent("Start the run name with a letter or digit");
      expect(requestsTo("/api/redteam/runs", "POST")).toHaveLength(0);
    });

    it("cannot start without a name", async () => {
      render(<RedTeamPage />);
      await screen.findByText(/No runs yet/);

      expect(screen.getByRole("button", { name: "Start run" })).toBeDisabled();
    });

    it("follows a running run every 2 seconds, then reloads the list when it is done", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      backend.job = job({ progress: 10 });
      render(<RedTeamPage />);
      expect(await screen.findByRole("status")).toHaveTextContent("10 of 72 attacks");
      const listLoadsBefore = requestsTo("/api/redteam/runs").length;

      backend.job = job({ progress: 40 });
      await act(() => vi.advanceTimersByTimeAsync(2000));
      expect(screen.getByRole("status")).toHaveTextContent("40 of 72 attacks");

      backend.job = job({ status: "complete", progress: 72, run_id: "eval-9" });
      backend.runs = [run({ id: "eval-9", name: "nlp-defense" })];
      await act(() => vi.advanceTimersByTimeAsync(2000));
      expect(await screen.findByText(/is done/)).toBeInTheDocument();
      expect(await screen.findByText("nlp-defense", { selector: ".lt-strong" })).toBeInTheDocument();
      expect(requestsTo("/api/redteam/runs").length).toBeGreaterThan(listLoadsBefore);
    });

    it("says when a run stopped with an error", async () => {
      backend.job = job({ status: "error", error: "promptfoo restarted during the run; start it again." });
      render(<RedTeamPage />);

      expect(await screen.findByText(/Run 'nlp-defense' stopped: promptfoo restarted/)).toBeInTheDocument();
    });
  });
});
