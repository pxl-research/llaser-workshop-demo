import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

import requests
import uvicorn
from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from AI.API import alerts, documents, embeddings, guardrails, metrics, readiness, rerankers, services, settings
from AI.API.exceptions import DocumentProcessingError, SystemNotReadyError
from AI.API.schemas import (
    AlertActionRequest,
    ConfigUpdateRequest,
    QueryRequest,
    ReadinessResponse,
    SecurityConfigResponse,
    SecurityConfigUpdateRequest,
    SystemInfoResponse,
    SystemPromptResponse,
    SystemPromptUpdateRequest,
)
from AI.API.uploads import normalize_upload_filename, save_upload_file


class OneLineFormatter(logging.Formatter):
    """Escapes CR/LF in messages, so request data (filenames, alert ids) cannot forge extra log lines."""

    def formatMessage(self, record):
        return super().formatMessage(record).replace("\r", "\\r").replace("\n", "\\n")


_log_handler = logging.StreamHandler()
_log_handler.setFormatter(OneLineFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_log_handler])
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Save plus indexing of one upload must not interleave with another: same-name uploads swap the file mid-parse.
# ponytail: global lock serializes all uploads; per-filename locks if uploads queue up.
_upload_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    services.start_background_warmup()
    if settings.USE_HOMEBREW:
        services.load_prompt_defense_async()
    if settings.USE_NLP_DEFENSE:
        services.load_nlp_defense_async()
    yield


app = FastAPI(title="RAG API", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=settings.CORS_METHODS,
    allow_headers=settings.CORS_HEADERS,
)


@app.get("/health")
def health_check():
    logger.debug("Health check requested")
    return {"status": "ok"}


@app.get("/ready", response_model=ReadinessResponse)
def get_readiness():
    """Return model-loading progress for the configured AI system."""
    try:
        return readiness.readiness.to_dict()
    except Exception:
        logger.exception("Failed to build readiness payload")
        return {
            "status": "loading",
            "components": {},
        }


def _require_ready_system():
    try:
        return services.get_system_instance()
    except SystemNotReadyError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc


@app.get("/security-config", response_model=SecurityConfigResponse)
def get_security_config():
    """Return current runtime security configuration."""
    threshold = 0.5
    try:
        detector = services.get_ml_safety_detector()
        if detector:
            threshold = getattr(detector, "confidence_threshold", 0.5)
    except Exception:
        pass

    homebrew_status, homebrew_error = services.get_homebrew_status()
    nlp_status, nlp_error = services.get_nlp_defense_status()

    return SecurityConfigResponse(
        use_homebrew=settings.USE_HOMEBREW,
        use_nlp_defense=settings.USE_NLP_DEFENSE,
        static_code_analysis_verified=settings.STATIC_CODE_ANALYSIS_VERIFIED,
        homebrew_status=homebrew_status,
        nlp_defense_status=nlp_status,
        homebrew_error=homebrew_error,
        homebrew_backend=services.get_homebrew_backend(),
        nlp_defense_error=nlp_error,
        nlp_confidence_threshold=threshold,
        max_upload_size_mb=settings.MAX_UPLOAD_SIZE_BYTES / (1024 * 1024),
        max_output_tokens=settings.RAG_MAX_OUTPUT_TOKENS,
        provider_timeout_seconds=settings.PROVIDER_TIMEOUT_SECONDS,
    )


@app.post("/security-config", response_model=SecurityConfigResponse)
def update_security_config(request: SecurityConfigUpdateRequest):
    """Update runtime security configuration."""
    logger.info("Security config update requested")

    if request.use_homebrew is not None:
        settings.USE_HOMEBREW = request.use_homebrew
        if request.use_homebrew:
            services.load_prompt_defense_async()
        else:
            services.disable_homebrew()
        logger.info("USE_HOMEBREW set to %s", request.use_homebrew)

    if request.use_nlp_defense is not None:
        settings.USE_NLP_DEFENSE = request.use_nlp_defense
        if request.use_nlp_defense:
            services.load_nlp_defense_async()
        else:
            services.disable_nlp_defense()
        logger.info("USE_NLP_DEFENSE set to %s", request.use_nlp_defense)

    if request.nlp_confidence_threshold is not None:
        try:
            detector = services.get_ml_safety_detector()
            if detector and hasattr(detector, "set_threshold"):
                detector.set_threshold(request.nlp_confidence_threshold)
                logger.info("NLP threshold set to %s", request.nlp_confidence_threshold)
        except Exception:
            logger.warning("Could not update NLP threshold: detector not available")

    if request.max_upload_size_mb is not None:
        settings.MAX_UPLOAD_SIZE_BYTES = int(request.max_upload_size_mb * 1024 * 1024)

    if request.max_output_tokens is not None:
        settings.RAG_MAX_OUTPUT_TOKENS = request.max_output_tokens

    if request.provider_timeout_seconds is not None:
        settings.PROVIDER_TIMEOUT_SECONDS = request.provider_timeout_seconds

    return get_security_config()


MAX_SYSTEM_PROMPT_CHARS = 8000


@app.get("/system-prompt", response_model=SystemPromptResponse)
def get_system_prompt():
    """Return the active chat system prompt and the default one."""
    return SystemPromptResponse(prompt=settings.SYSTEM_PROMPT, default_prompt=settings.DEFAULT_SYSTEM_PROMPT)


@app.post("/system-prompt", response_model=SystemPromptResponse)
def update_system_prompt(request: SystemPromptUpdateRequest):
    """Set the chat system prompt (runtime only); null resets it to the default."""
    prompt = settings.DEFAULT_SYSTEM_PROMPT if request.prompt is None else request.prompt
    if "{context}" not in prompt:
        raise HTTPException(status_code=422, detail="The prompt must contain {context}: that is where the documents go.")
    if len(prompt) > MAX_SYSTEM_PROMPT_CHARS:
        raise HTTPException(status_code=422, detail=f"The prompt is too long (at most {MAX_SYSTEM_PROMPT_CHARS} characters).")
    settings.SYSTEM_PROMPT = prompt
    logger.info("System prompt %s", "reset to default" if request.prompt is None else "updated")
    return get_system_prompt()


@app.get("/system-info", response_model=SystemInfoResponse)
def get_system_info():
    """Return current system type."""
    logger.info("System info requested - Type: %s", settings.SYSTEM_TYPE)
    return SystemInfoResponse(system_type=settings.SYSTEM_TYPE)


@app.get("/metrics")
def get_metrics():
    logger.debug("Metrics requested")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/available-llms")
def get_all_llms():
    logger.info("Fetching available LLMs from OpenRouter")
    try:
        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            timeout=settings.PROVIDER_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        models = response.json().get("data", [])
        # The OpenRouter account enforces Zero Data Retention; models without a ZDR endpoint fail every query.
        zdr = requests.get(
            "https://openrouter.ai/api/v1/endpoints/zdr",
            timeout=settings.PROVIDER_TIMEOUT_SECONDS,
        )
        zdr.raise_for_status()
        zdr_ids = {e.get("model_id") for e in zdr.json().get("data", [])}
    except requests.RequestException:
        logger.exception("Failed to fetch LLM models from provider")
        raise HTTPException(status_code=502, detail="Failed to fetch LLM models")
    except ValueError:
        logger.exception("Provider returned invalid LLM model data")
        raise HTTPException(status_code=502, detail="Failed to fetch LLM models")

    result = []
    for model in models:
        if model.get("id") not in zdr_ids:
            continue
        result.append(
            {
                "name": model.get("name"),
                "context_length": model.get("context_length"),
                "prompt_price": model.get("pricing", {}).get("prompt"),
                "completion_price": model.get("pricing", {}).get("completion"),
                "description": model.get("description"),
                "input_modalities": model.get("architecture", {}).get("input_modalities"),
                "id": model.get("id"),
            }
        )

    logger.debug("Retrieved %s LLM models", len(result))
    return result


def _env_fallback_config() -> dict:
    return {
        "llm": os.getenv("LLM", ""),
        "embedding_model": os.getenv("EMBEDDING_MODEL", ""),
        "reranker": os.getenv("RERANKER", ""),
    }


@app.get("/current-config")
def get_current_config():
    """Get the current model configuration."""
    logger.info("Current config requested")
    try:
        system = _require_ready_system()
        config = {}

        if hasattr(system, "get_current_llm"):
            config["llm"] = system.get_current_llm()
        if hasattr(system, "get_current_embedding_model"):
            config["embedding_model"] = system.get_current_embedding_model()
        if hasattr(system, "get_current_reranker_model"):
            config["reranker"] = system.get_current_reranker_model()

        if not config and hasattr(system, "get_current_config"):
            config = system.get_current_config()

        logger.debug("Current config: %s", config)
        return {"status": "success", "config": config}
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        logger.debug("System not ready; returning environment fallback config")
        return {"status": "loading", "config": _env_fallback_config()}
    except Exception:
        logger.exception("Failed to get current config")
        return {"status": "error", "message": "Failed to get current config", "config": _env_fallback_config()}


@app.get("/available-embeddings")
def get_available_embeddings():
    """Return list of available embedding models."""
    logger.debug("Available embeddings requested")
    return embeddings.AVAILABLE_EMBEDDINGS


@app.get("/available-rerankers")
def get_available_rerankers():
    """Return list of available reranker models."""
    logger.debug("Available rerankers requested")
    return rerankers.AVAILABLE_RERANKERS


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _event_stream(events) -> StreamingResponse:
    # X-Accel-Buffering stops the local nginx proxy from holding the stream back.
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _stream_answer(system, request: QueryRequest):
    stream = system.stream_query(request.question, session_id=request.session_id)
    try:
        while True:
            try:
                piece = next(stream)
            except StopIteration as stop:
                usage = stop.value or {}
                break
            yield _sse({"delta": piece})
    except Exception:
        logger.exception("Query processing failed")
        yield _sse({"error": "Query processing failed"})
        return

    run_total = usage.get("total_tokens", 0)
    metrics.tokens_used.inc(run_total)
    logger.info("Query processed successfully - Tokens used: %s", run_total)


@app.post("/query")
def query_rag(request: QueryRequest):
    logger.info("Query received - Session: %s", request.session_id)

    is_blocked, blocking_alert_id = alerts.is_session_blocked(request.session_id)
    if is_blocked:
        logger.warning(
            "Query blocked - Session %s blocked by alert %s",
            request.session_id,
            blocking_alert_id,
        )
        return _event_stream(iter([_sse({
            "delta": "Your session is currently blocked due to a pending malicious prompt alert. "
            "Please wait for the alert to be reviewed on the Alerts page."
        })]))

    metrics.total_queries.inc()
    blocked_response = guardrails.check_prompt_defenses(request)
    if blocked_response:
        return _event_stream(iter([_sse({"delta": blocked_response.answer})]))

    logger.info("Prompt passed all safety checks - Processing query for session %s", request.session_id)
    system = _require_ready_system()
    return _event_stream(_stream_answer(system, request))


@app.post("/update-config")
def update_configuration(request: ConfigUpdateRequest):
    """Update model configuration (LLM, embedding, reranker)."""
    logger.info("Update config requested - Type: %s", request.config_type)
    system = _require_ready_system()

    component_map = {"embedding": "embedding", "reranker": "reranker", "llm": "llm"}
    component_name = component_map.get(request.config_type)

    try:
        if component_name:
            readiness.readiness.set_component_loading(component_name, model=request.value)

        if request.config_type == "llm":
            result = system.update_llm(request.value)
        elif request.config_type == "embedding":
            result = system.update_embedding_model(request.value)
        elif request.config_type == "reranker":
            if not hasattr(system, "update_reranker"):
                raise HTTPException(status_code=400, detail="Reranker updates only available in RAG mode")
            result = system.update_reranker(request.value)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported config type: {request.config_type}")

        if component_name:
            readiness.readiness.set_component_ready(component_name, model=request.value)

        message = result.get("message")
        if result.get("status") == "error":
            # The message can carry exception text: log it, never return it
            logger.error("Config update failed - Type: %s - %s", request.config_type, message)
            message = "Configuration update failed"
        else:
            logger.info("Config update successful - Type: %s", request.config_type)
        return {
            "status": result.get("status"),
            "message": message,
            "config_type": request.config_type,
            "value": request.value,
            "documents_reembedded": result.get("documents_reembedded"),
            "chunks_reembedded": result.get("chunks_reembedded"),
            "reranker_updated": result.get("reranker_updated"),
        }
    except HTTPException:
        if component_name:
            readiness.readiness.set_component_ready(component_name)
        raise
    except Exception:
        if component_name:
            readiness.readiness.set_component_error(component_name, "Configuration update failed")
        logger.exception("Configuration update failed")
        raise HTTPException(status_code=500, detail="Configuration update failed")


@app.post("/upload-document")
async def upload_document(
    file: UploadFile = File(...),
):
    """Upload a document to the data folder and index it in the vector store."""
    logger.info("Document upload requested - Filename: %s", file.filename)

    if settings.SYSTEM_TYPE == "agent":
        logger.warning("Document upload attempted in Agent mode - request blocked")
        raise HTTPException(status_code=403, detail="Cannot upload documents in Agent mode")
    if not file.filename:
        logger.error("Document upload failed - No file provided")
        raise HTTPException(status_code=400, detail="No file provided")

    try:
        upload_dir = settings.UPLOAD_DIR
        upload_dir.mkdir(parents=True, exist_ok=True)

        safe_filename = normalize_upload_filename(file.filename)
        uploaded_file_path = upload_dir / safe_filename
        async with _upload_lock:
            uploaded_size = await save_upload_file(file, uploaded_file_path)

            system = _require_ready_system()
            if hasattr(system, "process_and_add_document"):
                return await run_in_threadpool(
                    documents.process_uploaded_documents,
                    system=system,
                    uploaded_file_path=uploaded_file_path,
                    uploaded_size=uploaded_size,
                )

        logger.info("Document upload successful (no processing) - Filename: %s", uploaded_file_path.name)
        return {
            "status": "success",
            "filename": uploaded_file_path.name,
            "size": uploaded_size,
            "path": str(uploaded_file_path),
            "message": "File saved to data folder (document processing capabilities not found on current system)",
        }
    except HTTPException:
        raise
    except DocumentProcessingError as exc:
        logger.exception("Document processing failed: %s", exc.user_message)
        raise HTTPException(status_code=exc.status_code, detail=exc.user_message) from None
    except Exception:
        logger.exception("Document upload failed")
        raise HTTPException(status_code=500, detail="Failed to upload file")


@app.get("/documents")
def list_documents():
    """List the uploaded documents, by filename."""
    upload_dir = settings.UPLOAD_DIR
    if not upload_dir.is_dir():
        return {"documents": []}
    # Hidden .part temp files and the store dir never match: .part is not an allowed extension, the store is a dir.
    allowed = settings.allowed_document_extensions()
    return {"documents": sorted(p.name for p in upload_dir.iterdir() if p.is_file() and p.suffix.lower() in allowed)}


@app.delete("/documents/{filename}")
async def delete_document(filename: str):
    """Delete an uploaded document from the data folder and the vector store."""
    logger.info("Document delete requested - Filename: %s", filename)

    if settings.SYSTEM_TYPE == "agent":
        raise HTTPException(status_code=403, detail="Cannot delete documents in Agent mode")

    file_path = settings.UPLOAD_DIR / normalize_upload_filename(filename)
    async with _upload_lock:
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Document not found")
        system = _require_ready_system()
        try:
            await run_in_threadpool(system.delete_document, str(file_path))
        except Exception:
            logger.exception("Document delete failed")
            raise HTTPException(status_code=500, detail="Failed to delete document")

    logger.info("Document deleted - Filename: %s", file_path.name)
    return {"status": "success", "filename": file_path.name, "message": f"Deleted {file_path.name}."}


@app.get("/prompt-alerts")
def get_prompt_alerts():
    """Get all malicious prompt alerts."""
    logger.info("Fetching alerts - Total alerts: %s", len(alerts.alerts_store))
    return {"alerts": list(alerts.alerts_store.values())}


@app.post("/prompt-alerts/{alert_id}")
def process_prompt_alert(alert_id: str, action_request: AlertActionRequest):
    """Process an alert action (accept or deny a malicious prompt)."""
    logger.info("Processing alert %s with action: %s", alert_id, action_request.action)

    if alert_id not in alerts.alerts_store:
        logger.error("Alert %s not found", alert_id)
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    success = alerts.process_alert_action(alert_id, action_request.action)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to process alert action")

    alert = alerts.alerts_store[alert_id]
    return {
        "status": "success",
        "alert_id": alert_id,
        "action": action_request.action,
        "alert_status": alert["status"],
        "message": f"Alert {action_request.action}ed successfully",
    }


@app.get("/prompt-alerts/{alert_id}")
def get_prompt_alert(alert_id: str):
    """Get a specific alert by ID."""
    if alert_id not in alerts.alerts_store:
        logger.error("Alert %s not found", alert_id)
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    return alerts.alerts_store[alert_id]


if __name__ == "__main__":
    logger.info("Starting API server...")
    # Local dev only; the Docker CMD binds 0.0.0.0 inside the container.
    uvicorn.run("api:app", host="127.0.0.1", port=8080, reload=True)
