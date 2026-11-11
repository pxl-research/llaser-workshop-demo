// Tests for runner.mjs: node --test promptfoo/runner.test.mjs   (Node 20 or later, no dependencies)
import assert from "node:assert/strict";
import { test } from "node:test";
import { evalIdFrom, finalStatus, promptfooArgs, requestProblem, totalAttacks } from "./runner.mjs";

const valid = { name: "nlp-defense", attack_set: "workshop", tags: { llm: "meta-llama/llama-3.3-70b-instruct", defenses: "llm+nlp", nlp_threshold: "0.5" } };

test("accepts a valid request", () => {
  assert.equal(requestProblem(valid), null);
  assert.equal(requestProblem({ name: "baseline", attack_set: "full" }), null);
  assert.equal(requestProblem({ name: "check-1", attack_set: "quick" }), null);
});

test("refuses names that are not simple run names", () => {
  for (const name of ["", "a b", "../etc", "x".repeat(65), "--config", "-x", ".hidden", 42, undefined]) {
    assert.equal(requestProblem({ ...valid, name }), "invalid run name", `name ${name}`);
  }
});

test("refuses unknown attack sets, so no other file can be read", () => {
  for (const attackSet of ["../../etc/passwd", "workshop.yaml", "", undefined]) {
    assert.equal(requestProblem({ ...valid, attack_set: attackSet }), "unknown attack set");
  }
});

test("refuses tags that could become options or odd values", () => {
  assert.equal(requestProblem({ ...valid, tags: { "--config": "x" } }), "invalid tag --config");
  assert.equal(requestProblem({ ...valid, tags: { llm: "a b" } }), "invalid tag llm");
  assert.equal(requestProblem({ ...valid, tags: { llm: 3 } }), "invalid tag llm");
  assert.equal(requestProblem({ ...valid, tags: ["llm=x"] }), "tags must be an object");
  assert.equal(requestProblem({ ...valid, tags: { run: "other" } }), "tag run is set by the runner");
});

test("refuses a body that is not an object", () => {
  assert.equal(requestProblem(null), "the body must be a JSON object");
  assert.equal(requestProblem("nlp-defense"), "the body must be a JSON object");
});

test("builds the same command as ./005_promptfoo_run.sh", () => {
  assert.deepEqual(promptfooArgs(valid), [
    "redteam", "eval",
    "-c", "/home/promptfoo/config/attack-sets/workshop.yaml",
    "--no-share",
    "--no-progress-bar",
    "--description", "nlp-defense",
    "--tag", "run=nlp-defense",
    "--tag", "attack_set=workshop",
    "--tag", "llm=meta-llama/llama-3.3-70b-instruct",
    "--tag", "defenses=llm+nlp",
    "--tag", "nlp_threshold=0.5",
  ]);
});

test("reads the number of attacks from the attack set header", () => {
  assert.equal(totalAttacks("# Generated: today\n#   Total cases: 72\ndescription: x\n"), 72);
  assert.equal(totalAttacks("description: no header\n"), 0);
});

test("finds the run id in promptfoo's output", () => {
  assert.equal(evalIdFrom("noise\nStarting evaluation eval-W9P-2026-11-11T12:18:22\nRunning 24 test cases"), "eval-W9P-2026-11-11T12:18:22");
  assert.equal(evalIdFrom("still loading"), null);
});

test("counts exit code 100 (attacks got through) as a finished run", () => {
  assert.equal(finalStatus(0), "complete");
  assert.equal(finalStatus(100), "complete");
  assert.equal(finalStatus(1), "error");
  assert.equal(finalStatus(null), "error");
});
