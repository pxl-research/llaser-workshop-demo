"""The promptfoo red-team runs, for the Automated red teaming page.

The browser never talks to promptfoo's API: promptfoo has no login and allows every website.
Only this module does, inside the compose network. It
- lists the runs, a few fields per run (the attacks and LLASER's answers stay in promptfoo,
  where the promptfoo UI shows them);
- starts a run of one of the committed attack sets and follows its progress, through the promptfoo-runner
  service (promptfoo/runner.mjs). The runner runs the same command as ./005_promptfoo_run.sh, so promptfoo
  cloud grades the answers; promptfoo's own job API cannot do that. One run at a time.
"""

import logging
from typing import Optional
from urllib.parse import quote

import requests

from AI.API import settings
from AI.API.schemas import RedteamJob, RedteamRun, SecurityConfigResponse

logger = logging.getLogger(__name__)

# Tags that describe the run itself; the other tags are LLASER's settings during the run.
RUN_TAGS = {"run", "attack_set"}


class PromptfooUnavailableError(Exception):
    """promptfoo is not running, or answered with something unexpected."""


class RunRefusedError(Exception):
    """A run cannot start now; the message says why and what to do about it."""


# --- Listing the runs ---------------------------------------------------------------------------


def list_runs() -> list[RedteamRun]:
    """All red-team runs, newest first. Smoke checks (./003_promptfoo_check.sh) are left out."""
    runs = _get_json("/api/results").get("data", [])
    red_team_runs = [run for run in runs if run.get("isRedteam")]
    try:
        summaries = [_summarize(run) for run in red_team_runs]
    except (KeyError, IndexError, TypeError) as error:
        # Another promptfoo version may answer differently; the image is pinned for that reason.
        raise PromptfooUnavailableError("promptfoo returned runs in an unexpected format") from error
    return sorted(summaries, key=lambda run: run.created_at, reverse=True)


def _summarize(run: dict) -> RedteamRun:
    run_id = run["evalId"]
    # One row is enough: the header holds the counts, the config holds the tags.
    table = _get_json(f"/api/eval/{quote(run_id, safe='')}/table?limit=1")
    counts = table["table"]["head"]["prompts"][0]["metrics"]
    tags = {name: str(value) for name, value in (table.get("config", {}).get("tags") or {}).items()}

    return RedteamRun(
        id=run_id,
        name=run.get("description") or run_id,
        created_at=run["createdAt"],
        attack_set=tags.get("attack_set"),
        settings={name: value for name, value in tags.items() if name not in RUN_TAGS},
        attacks=run.get("numTests", 0),
        # promptfoo counts an attack as failed when it got through.
        got_through=counts.get("testFailCount", 0),
        errors=counts.get("testErrorCount", 0),
    )


# --- LLASER's settings, recorded with every run -----------------------------------------------
# The same tags as promptfoo/run-tags.mjs, which ./005_promptfoo_run.sh uses; keep the two in step.


def settings_tags(config: SecurityConfigResponse, llm: str, prompt_is_default: bool) -> dict[str, str]:
    """LLASER's current settings as run tags, e.g. {"llm": ..., "defenses": "nlp", "prompt": "default"}."""
    active = [name for name, on in (("llm", config.use_homebrew), ("nlp", config.use_nlp_defense)) if on]
    tags = {
        "llm": llm,
        "defenses": "+".join(active) or "off",
        "prompt": "default" if prompt_is_default else "custom",
    }
    if config.use_nlp_defense:
        tags["nlp_threshold"] = str(config.nlp_confidence_threshold)
    if config.use_homebrew:
        tags["llm_defense_backend"] = config.homebrew_backend or "unknown"
    return tags


def defense_problems(config: SecurityConfigResponse) -> list[str]:
    """Defenses that are on but not working: they block every question, so a run would measure nothing."""
    problems = []
    if config.use_homebrew and config.homebrew_status != "ready":
        problems.append(f"the LLM defense is {config.homebrew_status}")
    if config.use_nlp_defense and config.nlp_defense_status != "ready":
        problems.append(f"the NLP defense is {config.nlp_defense_status}")
    return problems


# --- Starting a run and following it ---------------------------------------------------------


def start_run(name: str, attack_set: str, tags: dict[str, str]) -> RedteamJob:
    """Starts a run of a committed attack set; raises RunRefusedError when it cannot start now."""
    if name in _used_run_names():
        raise RunRefusedError(f"There already is a run named '{name}'. Choose a name that says what you changed.")
    if not _grading_email_is_set():
        raise RunRefusedError(
            "promptfoo needs an e-mail address to grade the answers. Set it once with: "
            "docker compose exec promptfoo promptfoo config set email <your-email>"
        )

    response = _runner("POST", "/runs", {"name": name, "attack_set": attack_set, "tags": tags})
    if response.status_code == 409:
        # The runner allows one run at a time.
        raise RunRefusedError(f"{response.json().get('error', 'Another run is still going')}. Wait until it is done.")
    _check(response, "POST /runs")
    logger.info("Red-team run %s started (%s attack set)", name, attack_set)
    return current_job()


def current_job() -> Optional[RedteamJob]:
    """The run started last from the page and how far it is, or None when none was started."""
    response = _runner("GET", "/runs/current")
    _check(response, "GET /runs/current")
    run = _json(response, "GET /runs/current").get("run")
    if run is None:
        return None
    try:
        return RedteamJob(**{field: run.get(field) for field in RedteamJob.model_fields})
    except ValueError as error:
        raise PromptfooUnavailableError("the runner returned a run in an unexpected format") from error


def _used_run_names() -> set[str]:
    return {run.get("description") for run in _get_json("/api/results").get("data", [])}


def _grading_email_is_set() -> bool:
    # Only whether it is set: the address itself never leaves this module.
    return "@" in str(_get_json("/api/user/email").get("email") or "")


def _runner(method: str, path: str, body: Optional[dict] = None) -> requests.Response:
    try:
        return requests.request(method, f"{settings.PROMPTFOO_RUNNER_URL}{path}", json=body, timeout=settings.PROVIDER_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        raise PromptfooUnavailableError(f"runner {method} {path} failed") from error


# --- promptfoo's web server ---------------------------------------------------------------------


def _get_json(path: str) -> dict:
    """GET from promptfoo's web server, which holds the runs."""
    try:
        response = requests.request("GET", f"{settings.PROMPTFOO_URL}{path}", timeout=settings.PROVIDER_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        raise PromptfooUnavailableError(f"GET {path} failed") from error
    _check(response, f"GET {path}")
    return _json(response, f"GET {path}")


def _check(response: requests.Response, what: str) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        raise PromptfooUnavailableError(f"{what} answered HTTP {response.status_code}") from error


def _json(response: requests.Response, what: str) -> dict:
    try:
        return response.json()
    except ValueError as error:
        raise PromptfooUnavailableError(f"{what} returned no JSON") from error
