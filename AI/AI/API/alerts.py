import logging
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional


logger = logging.getLogger(__name__)

alerts_store: Dict[str, dict] = {}
session_blocks: Dict[str, str] = {}
# Requests run in a thread pool, so two releases of the same alert can run at the same time.
# The lock makes "check not released, then mark released" one step: each accepted prompt is answered once.
# Only claim_accepted_prompt takes it, and it holds it for a few dict reads and writes, so it cannot deadlock.
_lock = threading.Lock()


def create_malicious_prompt_alert(
    prompt: str,
    risk_level: str,
    threat_types: List[str],
    session_id: Optional[str] = None,
) -> str:
    """Create a new alert for a malicious prompt and block the session."""
    alert_id = str(uuid.uuid4())
    alert = {
        "id": alert_id,
        "prompt": prompt,
        "timestamp": datetime.utcnow().isoformat(),
        "riskLevel": risk_level,
        "threatTypes": threat_types,
        "sessionID": session_id,
        "status": "pending",
        # Set once the chat fetched the answer to an accepted prompt.
        "released": False,
    }

    alerts_store[alert_id] = alert

    if session_id:
        session_blocks[session_id] = alert_id

    logger.warning(
        "Malicious prompt detected - Alert ID: %s, Risk Level: %s, Session: %s",
        alert_id,
        risk_level,
        session_id,
    )

    return alert_id


def is_session_blocked(session_id: Optional[str]) -> tuple[bool, Optional[str]]:
    """Check if a session is blocked due to a pending malicious prompt alert."""
    if not session_id:
        return False, None

    alert_id = session_blocks.get(session_id)
    if alert_id and alerts_store.get(alert_id, {}).get("status") == "pending":
        return True, alert_id

    return False, None


def process_alert_action(alert_id: str, action: str) -> bool:
    """Process an alert action (accept or deny)."""
    if alert_id not in alerts_store:
        logger.error("Alert %s not found", alert_id)
        return False

    alert = alerts_store[alert_id]
    if action == "accept":
        alert["status"] = "accepted"
        logger.info("Alert %s accepted - prompt approved, its chat may fetch the answer", alert_id)
        return True

    if action == "deny":
        alert["status"] = "denied"
        session_id = alert.get("sessionID")
        if session_id:
            session_blocks.pop(session_id, None)
        logger.info("Alert %s denied - session %s unblocked", alert_id, session_id)
        return True

    logger.error("Unknown action '%s' for alert %s", action, alert_id)
    return False


def claim_accepted_prompt(alert_id: str, session_id: str) -> Optional[str]:
    """Return an accepted alert's prompt once, and only to the session it was blocked in."""
    with _lock:
        alert = alerts_store.get(alert_id)
        if (
            alert is None
            or alert["status"] != "accepted"
            or alert["released"]
            or not alert.get("sessionID")
            or alert["sessionID"] != session_id
        ):
            return None
        alert["released"] = True
        return alert["prompt"]
