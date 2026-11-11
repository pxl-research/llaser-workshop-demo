// Prints the current LLASER settings as promptfoo tags, one "name=value" per line,
// so every red-team run records what it measured. Runs inside the promptfoo container:
//   node /home/promptfoo/config/run-tags.mjs
// Exits with an error when a defense is switched on but not working: such a run measures nothing useful.

const BACKEND = "http://backend:8080";

const getJson = async (path) => {
  const response = await fetch(`${BACKEND}${path}`);
  if (!response.ok) throw new Error(`GET ${path} failed: HTTP ${response.status}`);
  return response.json();
};

// "off", "llm", "nlp" or "llm+nlp".
const defensesTag = (security) => {
  const active = [];
  if (security.use_homebrew) active.push("llm");
  if (security.use_nlp_defense) active.push("nlp");
  return active.length === 0 ? "off" : active.join("+");
};

// A defense that is on must be ready, otherwise it blocks every question (fail closed).
const defenseProblems = (security) => {
  const problems = [];
  if (security.use_homebrew && security.homebrew_status !== "ready") {
    problems.push(`LLM defense is ${security.homebrew_status}`);
  }
  if (security.use_nlp_defense && security.nlp_defense_status !== "ready") {
    problems.push(`NLP defense is ${security.nlp_defense_status}`);
  }
  return problems;
};

const main = async () => {
  const security = await getJson("/security-config");
  const { llm } = await getJson("/llm");
  const { prompt, default_prompt: defaultPrompt } = await getJson("/system-prompt");

  const problems = defenseProblems(security);
  if (problems.length > 0) {
    console.error(`Not starting the run: ${problems.join(", ")}. Wait until it shows Active on the Controls page.`);
    process.exit(1);
  }

  const tags = {
    llm,
    defenses: defensesTag(security),
    prompt: prompt === defaultPrompt ? "default" : "custom",
  };
  if (security.use_nlp_defense) tags.nlp_threshold = security.nlp_confidence_threshold;
  if (security.use_homebrew) tags.llm_defense_backend = security.homebrew_backend ?? "unknown";

  for (const [name, value] of Object.entries(tags)) console.log(`${name}=${value}`);
};

main().catch((error) => {
  console.error(`Could not read the LLASER settings: ${error.message}`);
  process.exit(1);
});
