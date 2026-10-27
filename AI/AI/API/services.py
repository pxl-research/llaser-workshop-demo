import logging
import threading

from AI.API import settings
from AI.API.Agent import Agent
from AI.API.exceptions import SystemNotReadyError
from AI.API.readiness import readiness
from AI.API.RAG import RAG


logger = logging.getLogger(__name__)

_system_instance = None
_prompt_defense = None
_ml_safety_detector = None
_warmup_started = False
_warmup_lock = threading.Lock()


def _handle_component_progress(component: str, state: str, model: str | None, message: str | None):
    if state == "loading":
        readiness.set_component_loading(component, model=model)
        return
    if state == "ready":
        readiness.set_component_ready(component, model=model)
        return
    if state == "skipped":
        readiness.set_component_skipped(component, message=message)
        return
    if state == "error":
        readiness.set_component_error(component, message or "Component failed to load")
        raise RuntimeError(message or f"{component} failed to load")


def _create_system_instance():
    on_progress = _handle_component_progress

    if settings.SYSTEM_TYPE == "rag":
        return RAG(on_progress=on_progress)
    if settings.SYSTEM_TYPE == "agent":
        return Agent(on_progress=on_progress)

    raise RuntimeError(f"Unsupported SYSTEM_TYPE: {settings.SYSTEM_TYPE}")


def _warmup_worker():
    global _system_instance

    try:
        instance = _create_system_instance()
        _system_instance = instance
        readiness.mark_ready()
        logger.info("AI system warmup completed")
    except Exception as exc:
        logger.exception("AI system warmup failed")
        if not readiness.is_error():
            readiness.mark_error(str(exc))


def start_background_warmup():
    global _warmup_started

    if not settings.BACKGROUND_WARMUP:
        return

    with _warmup_lock:
        if _warmup_started:
            return
        _warmup_started = True

    readiness.reset_for_system_type(settings.SYSTEM_TYPE)
    thread = threading.Thread(target=_warmup_worker, name="ai-system-warmup", daemon=True)
    thread.start()
    logger.info("Started background AI system warmup")


def get_system_instance():
    """Get the configured system instance, or raise if warmup is still running."""
    global _system_instance

    if _system_instance is not None:
        return _system_instance

    if settings.BACKGROUND_WARMUP:
        if readiness.is_error():
            raise SystemNotReadyError(readiness.error_message() or "System failed to start")
        raise SystemNotReadyError("System is still starting")

    _system_instance = _create_system_instance()
    readiness.reset_for_system_type(settings.SYSTEM_TYPE)
    readiness.mark_ready()
    return _system_instance


_homebrew_status = "off"  # off | loading | ready | error
_homebrew_error: str | None = None
_nlp_defense_status = "off"  # off | loading | ready | error
_nlp_defense_error: str | None = None


def get_homebrew_status() -> tuple[str, str | None]:
    return _homebrew_status, _homebrew_error


def get_nlp_defense_status() -> tuple[str, str | None]:
    return _nlp_defense_status, _nlp_defense_error


def get_prompt_defense():
    """Get or create the prompt defense instance."""
    global _prompt_defense
    if _prompt_defense is None:
        from AI.API.Prompt_Defense import PromptDefense

        _prompt_defense = PromptDefense()
    return _prompt_defense


def get_ml_safety_detector():
    """Get or create the ML-based safety detector instance."""
    global _ml_safety_detector
    if _ml_safety_detector is None:
        from AI.API.Prompt_Defense_NLP import create_ml_safety_detector

        _ml_safety_detector = create_ml_safety_detector()
    return _ml_safety_detector


def load_prompt_defense_async():
    """Load the homebrew prompt defense model in a background thread."""
    global _prompt_defense, _homebrew_status, _homebrew_error

    if _homebrew_status == "loading":
        return
    if _homebrew_status == "ready" and _prompt_defense is not None:
        return

    _homebrew_status = "loading"
    _homebrew_error = None

    def _worker():
        global _prompt_defense, _homebrew_status, _homebrew_error
        try:
            from AI.API.Prompt_Defense import PromptDefense
            _prompt_defense = PromptDefense()
            _homebrew_status = "ready"
            logger.info("Homebrew prompt defense loaded")
        except Exception as exc:
            logger.exception("Failed to load homebrew prompt defense")
            _homebrew_status = "error"
            _homebrew_error = str(exc)

    thread = threading.Thread(target=_worker, name="homebrew-defense-load", daemon=True)
    thread.start()


def load_nlp_defense_async():
    """Load the NLP/ML prompt defense model in a background thread."""
    global _ml_safety_detector, _nlp_defense_status, _nlp_defense_error

    if _nlp_defense_status == "loading":
        return
    if _nlp_defense_status == "ready" and _ml_safety_detector is not None:
        return

    _nlp_defense_status = "loading"
    _nlp_defense_error = None

    def _worker():
        global _ml_safety_detector, _nlp_defense_status, _nlp_defense_error
        try:
            from AI.API.Prompt_Defense_NLP import create_ml_safety_detector
            _ml_safety_detector = create_ml_safety_detector()
            if _ml_safety_detector and _ml_safety_detector.is_loaded:
                _nlp_defense_status = "ready"
                logger.info("NLP prompt defense loaded")
            else:
                _nlp_defense_status = "error"
                _nlp_defense_error = (
                    getattr(_ml_safety_detector, "load_error", None)
                    or "NLP defense model is not available on this deployment"
                )
                logger.warning("NLP prompt defense unavailable: %s", _nlp_defense_error)
        except Exception as exc:
            logger.exception("Failed to load NLP prompt defense")
            _nlp_defense_status = "error"
            _nlp_defense_error = str(exc)

    thread = threading.Thread(target=_worker, name="nlp-defense-load", daemon=True)
    thread.start()


def disable_homebrew():
    """Mark homebrew defense as off."""
    global _homebrew_status, _homebrew_error
    _homebrew_status = "off"
    _homebrew_error = None


def disable_nlp_defense():
    """Mark NLP defense as off."""
    global _nlp_defense_status, _nlp_defense_error
    _nlp_defense_status = "off"
    _nlp_defense_error = None
