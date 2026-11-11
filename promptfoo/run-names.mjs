// Prints the names of the earlier runs, one per line, so ./005_promptfoo_run.sh can refuse a name
// that is already taken. Runs inside the promptfoo container:
//   node /home/promptfoo/config/run-names.mjs
// The name of a run is its description (005 passes it with --description).

const PROMPTFOO_SERVER = "http://localhost:3000";

const main = async () => {
  const response = await fetch(`${PROMPTFOO_SERVER}/api/results`);
  if (!response.ok) throw new Error(`GET /api/results failed: HTTP ${response.status}`);
  const { data: runs } = await response.json();

  for (const run of runs) {
    if (run.description) console.log(run.description);
  }
};

main().catch((error) => {
  console.error(`Could not read the earlier runs: ${error.message}`);
  process.exit(1);
});
