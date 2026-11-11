// Starts red-team runs for the LLASER backend: the same command as ./005_promptfoo_run.sh,
// so promptfoo cloud grades the answers (promptfoo only does that from its command line).
//
// Runs in its own container (service promptfoo-runner) on the compose network, without a published port:
// only the backend calls it. One run at a time.
//   POST /runs           {"name": "nlp-defense", "attack_set": "quick" | "workshop" | "full", "tags": {"llm": "...", ...}}
//   GET  /runs/current   the run started last: status, progress, total
//
// promptfoo is started without a shell and with a fixed argument list; the request only fills in
// a checked name, one of three attack sets and checked tags.

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { pathToFileURL } from "node:url";

const PORT = 3100;
const CONFIG_DIR = "/home/promptfoo/config";
// promptfoo's web server: it lists the results of a run while the run is going.
const PROMPTFOO_SERVER = process.env.PROMPTFOO_SERVER ?? "http://promptfoo:3000";

const ATTACK_SETS = ["quick", "workshop", "full"];
// Starts with a letter or digit, so a name can never look like an option ("--config").
const RUN_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const TAG_NAME = /^[a-z_]{1,32}$/;
const TAG_VALUE = /^[A-Za-z0-9._:/+-]{1,128}$/;
// Exit code 100 means some attacks got through: that is a result, not an error.
const ATTACKS_GOT_THROUGH = 100;

// --- Checking a request and building the command (pure, tested in runner.test.mjs) ---

// The reason a request is refused, or null when it is fine.
export const requestProblem = (body) => {
  if (typeof body !== "object" || body === null) return "the body must be a JSON object";
  const { name, attack_set: attackSet, tags = {} } = body;
  if (typeof name !== "string" || !RUN_NAME.test(name)) return "invalid run name";
  if (!ATTACK_SETS.includes(attackSet)) return "unknown attack set";
  if (typeof tags !== "object" || tags === null || Array.isArray(tags)) return "tags must be an object";
  for (const [tagName, value] of Object.entries(tags)) {
    if (!TAG_NAME.test(tagName) || typeof value !== "string" || !TAG_VALUE.test(value)) return `invalid tag ${tagName}`;
    if (tagName === "run" || tagName === "attack_set") return `tag ${tagName} is set by the runner`;
  }
  return null;
};

export const attackSetFile = (attackSet) => `${CONFIG_DIR}/attack-sets/${attackSet}.yaml`;

// The same command as ./005_promptfoo_run.sh.
export const promptfooArgs = ({ name, attack_set: attackSet, tags = {} }) => {
  const allTags = { run: name, attack_set: attackSet, ...tags };
  return [
    "redteam", "eval",
    "-c", attackSetFile(attackSet),
    "--no-share",
    "--no-progress-bar",
    "--description", name,
    ...Object.entries(allTags).flatMap(([tagName, value]) => ["--tag", `${tagName}=${value}`]),
  ];
};

// The number of attacks, from the header ./004_promptfoo_generate.sh writes ("#   Total cases: 72").
export const totalAttacks = (attackSetText) => Number(/^#\s+Total cases:\s+(\d+)/m.exec(attackSetText)?.[1] ?? 0);

// promptfoo prints "Starting evaluation eval-AbC-2026-11-11T12:18:22" when the run begins.
export const evalIdFrom = (output) => /Starting evaluation (eval-[A-Za-z0-9:._-]+)/.exec(output)?.[1] ?? null;

export const finalStatus = (exitCode) => (exitCode === 0 || exitCode === ATTACKS_GOT_THROUGH ? "complete" : "error");

// --- The run ---

// The run started last: { name, attack_set, status, total, evalId, error }.
let current = null;

const startRun = (request) => {
  const run = {
    name: request.name,
    attack_set: request.attack_set,
    status: "running",
    total: totalAttacks(readFileSync(attackSetFile(request.attack_set), "utf8")),
    evalId: null,
    error: null,
  };
  current = run;

  const child = spawn("promptfoo", promptfooArgs(request), { stdio: ["ignore", "pipe", "pipe"] });
  let output = "";
  const collect = (chunk) => {
    process.stdout.write(chunk); // docker compose logs promptfoo-runner
    if (run.evalId === null) {
      output += chunk;
      run.evalId = evalIdFrom(output);
    }
  };
  child.stdout.on("data", collect);
  child.stderr.on("data", collect);
  child.on("error", (error) => {
    run.status = "error";
    run.error = `promptfoo could not start: ${error.message}`;
  });
  child.on("close", (exitCode) => {
    run.status = finalStatus(exitCode);
    if (run.status === "error") run.error ??= `promptfoo stopped with exit code ${exitCode}; see: docker compose logs promptfoo-runner`;
  });
};

// How many attacks have a result so far, from promptfoo's web server.
const progressOf = async (run) => {
  if (run.status === "complete") return run.total;
  if (run.evalId === null) return 0;
  try {
    const response = await fetch(`${PROMPTFOO_SERVER}/api/results`);
    const { data } = await response.json();
    return data.find((result) => result.evalId === run.evalId)?.numTests ?? 0;
  } catch {
    return 0;
  }
};

// --- HTTP ---

const send = (response, status, body) => {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(body));
};

const readJson = async (request) => {
  let text = "";
  for await (const chunk of request) {
    text += chunk;
    if (text.length > 10_000) throw new Error("request too large");
  }
  return JSON.parse(text);
};

const handle = async (request, response) => {
  if (request.method === "GET" && request.url === "/runs/current") {
    if (current === null) return send(response, 200, { run: null });
    const { evalId, ...run } = current;
    return send(response, 200, { run: { ...run, run_id: evalId, progress: await progressOf(current) } });
  }

  if (request.method === "POST" && request.url === "/runs") {
    let body;
    try {
      body = await readJson(request);
    } catch {
      return send(response, 400, { error: "the body must be JSON, at most 10 KB" });
    }
    const problem = requestProblem(body);
    if (problem) return send(response, 400, { error: problem });
    if (current?.status === "running") return send(response, 409, { error: `the run '${current.name}' is still going` });
    startRun(body);
    return send(response, 202, { started: body.name });
  }

  return send(response, 404, { error: "not found" });
};

// Only when started as a program, not when the tests import the functions above.
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  createServer((request, response) => {
    handle(request, response).catch((error) => send(response, 500, { error: String(error) }));
  }).listen(PORT, () => console.log(`promptfoo runner listening on ${PORT}`));
}
