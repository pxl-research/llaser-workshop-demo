import logging
from typing import List, Optional

import requests

from AI.API import alerts, metrics, services, settings
from AI.API.schemas import QueryRequest, QueryResponse


logger = logging.getLogger(__name__)

DEFENSE_UNAVAILABLE_ANSWER = "query blocked: prompt defense unavailable, try again later"


def blocked_query_response(
    prompt: str,
    session_id: Optional[str],
    risk_level: str,
    threat_types: List[str],
) -> QueryResponse:
    metrics.malicious_prompt_count.inc()
    alerts.create_malicious_prompt_alert(
        prompt=prompt,
        risk_level=risk_level,
        threat_types=threat_types,
        session_id=session_id,
    )
    return QueryResponse(answer="query blocked")


def defense_unavailable_response() -> QueryResponse:
    """Block one query because a defense is down: no alert or session block, the user did nothing wrong."""
    metrics.prompt_defense_unavailable.inc()
    return QueryResponse(answer=DEFENSE_UNAVAILABLE_ANSWER)


def _classify_with_failover(question: str) -> tuple[bool, str]:
    """A network or HTTP failure on the Spark switches the defense to OpenRouter and retries once."""
    detector = services.get_prompt_defense()
    try:
        return detector.check_prompt_safety(question)
    except requests.RequestException:
        if services.get_homebrew_backend() != "spark":
            raise
        logger.warning("DGX Spark defense failed, switching to OpenRouter", exc_info=True)
        return services.switch_prompt_defense_to_openrouter().check_prompt_safety(question)


def check_homebrew_prompt_defense(request: QueryRequest) -> Optional[QueryResponse]:
    if not settings.USE_HOMEBREW:
        return None

    homebrew_status, _ = services.get_homebrew_status()
    if homebrew_status != "ready":
        logger.warning("Homebrew defense enabled but %s, query blocked", homebrew_status)
        if homebrew_status == "error":
            services.load_prompt_defense_async()
        return defense_unavailable_response()

    logger.debug("Checking prompt with homebrew defense")
    try:
        is_safe, reason = _classify_with_failover(request.question)
    except Exception:
        logger.exception("Homebrew prompt defense failed closed")
        return defense_unavailable_response()

    if is_safe:
        return None

    logger.warning("Malicious prompt detected by homebrew defense")
    return blocked_query_response(
        prompt=request.question,
        session_id=request.session_id,
        risk_level="high",
        threat_types=[reason] if reason else ["Unknown threat"],
    )


def check_nlp_prompt_defense(request: QueryRequest) -> Optional[QueryResponse]:
    if not settings.USE_NLP_DEFENSE:
        return None

    nlp_status, _ = services.get_nlp_defense_status()
    if nlp_status != "ready":
        logger.warning("NLP defense enabled but %s, query blocked", nlp_status)
        return defense_unavailable_response()

    logger.debug("Checking prompt with NLP defense")
    try:
        detector = services.get_ml_safety_detector()
        if not detector.is_loaded:
            logger.error("NLP prompt defense is enabled but model is not loaded")
            return defense_unavailable_response()

        result = detector.detect(request.question)
    except Exception:
        logger.exception("NLP prompt defense failed closed")
        return defense_unavailable_response()

    if not result.get("is_malicious"):
        return None

    logger.warning(
        "Malicious prompt detected by NLP defense - Risk: %s, Confidence: %s",
        result.get("risk_level"),
        result.get("confidence"),
    )
    risk_level = str(result.get("risk_level", "unknown")).lower()
    threat_types = result.get("threat_types", ["Unknown threat type"])
    return blocked_query_response(
        prompt=request.question,
        session_id=request.session_id,
        risk_level=risk_level,
        threat_types=threat_types,
    )


def check_prompt_defenses(request: QueryRequest) -> Optional[QueryResponse]:
    for prompt_check in (check_homebrew_prompt_defense, check_nlp_prompt_defense):
        blocked_response = prompt_check(request)
        if blocked_response:
            return blocked_response
    return None
