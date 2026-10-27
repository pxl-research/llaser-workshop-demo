from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading
from typing import Any


class ComponentState(str, Enum):
    PENDING = "pending"
    LOADING = "loading"
    READY = "ready"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class ComponentStatus:
    state: ComponentState = ComponentState.PENDING
    model: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"state": self.state.value}
        if self.model is not None:
            payload["model"] = self.model
        if self.message is not None:
            payload["message"] = self.message
        return payload


class ReadinessTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = ComponentState.PENDING
        self._error_message: str | None = None
        self._components: dict[str, ComponentStatus] = {}

    def reset_for_system_type(self, system_type: str) -> None:
        with self._lock:
            self._status = ComponentState.LOADING
            self._error_message = None
            if system_type == "rag":
                component_names = ("embedding", "reranker", "vector_store", "llm")
            elif system_type == "agent":
                component_names = ("embedding", "llm")
            else:
                component_names = ("system",)
            self._components = {name: ComponentStatus() for name in component_names}

    def set_component_loading(self, name: str, *, model: str | None = None) -> None:
        with self._lock:
            component = self._components.setdefault(name, ComponentStatus())
            component.state = ComponentState.LOADING
            component.model = model
            component.message = None
            if self._status == ComponentState.READY:
                self._status = ComponentState.LOADING

    def set_component_ready(self, name: str, *, model: str | None = None) -> None:
        with self._lock:
            component = self._components.setdefault(name, ComponentStatus())
            component.state = ComponentState.READY
            component.model = model
            component.message = None
            if self._status == ComponentState.LOADING and self._all_terminal():
                self._status = ComponentState.READY

    def _all_terminal(self) -> bool:
        """True when every tracked component is in a terminal state (ready/skipped/error)."""
        return all(
            c.state in (ComponentState.READY, ComponentState.SKIPPED, ComponentState.ERROR)
            for c in self._components.values()
        )

    def set_component_skipped(self, name: str, *, message: str | None = None) -> None:
        with self._lock:
            component = self._components.setdefault(name, ComponentStatus())
            component.state = ComponentState.SKIPPED
            component.message = message

    def set_component_error(self, name: str, message: str) -> None:
        with self._lock:
            component = self._components.setdefault(name, ComponentStatus())
            component.state = ComponentState.ERROR
            component.message = message
            self._status = ComponentState.ERROR
            self._error_message = message

    def mark_ready(self) -> None:
        with self._lock:
            self._status = ComponentState.READY
            self._error_message = None

    def mark_error(self, message: str) -> None:
        with self._lock:
            self._status = ComponentState.ERROR
            self._error_message = message

    def is_ready(self) -> bool:
        with self._lock:
            return self._status == ComponentState.READY

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
