from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading
from typing import Any


class ComponentState(str, Enum):
    PENDING = "pending"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"


@dataclass
class ComponentStatus:
    state: ComponentState = ComponentState.PENDING
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"state": self.state.value}
        if self.model is not None:
            payload["model"] = self.model
        return payload


class ReadinessTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = ComponentState.PENDING
        self._error_message: str | None = None
        self._components: dict[str, ComponentStatus] = {}

    def reset(self) -> None:
        with self._lock:
            self._status = ComponentState.LOADING
            self._error_message = None
            self._components = {
                name: ComponentStatus() for name in ("embedding", "reranker", "vector_store", "llm")
            }

    def set_component_loading(self, name: str, *, model: str | None = None) -> None:
        self._set_component(name, ComponentState.LOADING, model)

    def set_component_ready(self, name: str, *, model: str | None = None) -> None:
        self._set_component(name, ComponentState.READY, model)

    def _set_component(self, name: str, state: ComponentState, model: str | None) -> None:
        with self._lock:
            self._components[name] = ComponentStatus(state, model)

    def mark_ready(self) -> None:
        with self._lock:
            self._status = ComponentState.READY
            self._error_message = None

    def mark_error(self, message: str) -> None:
        with self._lock:
            self._status = ComponentState.ERROR
            self._error_message = message

    def is_error(self) -> bool:
        with self._lock:
            return self._status == ComponentState.ERROR

    def error_message(self) -> str | None:
        with self._lock:
            return self._error_message

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            payload: dict[str, Any] = {
                "status": self._status.value,
                "components": {
                    name: component.to_dict() for name, component in self._components.items()
                },
            }
            if self._error_message:
                payload["message"] = self._error_message
            return payload


readiness = ReadinessTracker()
