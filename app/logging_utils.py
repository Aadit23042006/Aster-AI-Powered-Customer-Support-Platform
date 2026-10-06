"""Plain structured JSONL logging. One line per conversational turn, with
everything the assignment's observability section asks for. No dashboard,
no secrets logged (API keys are never written; order lookup results already
went through the field allowlist before they got here).
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app import config
from app.security.pii import redact_pii

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunkTrace:
    source_file: str
    heading: str
    score: float
    is_active_official: bool


@dataclass
class ToolCallTrace:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]  # already sanitized by app/orders.py before it gets here


@dataclass
class TurnTrace:
    timestamp: float
    session_id: str
    user_message: str
    history_included: list[dict[str, str]]
    retrieved: list[RetrievedChunkTrace]
    conflict_detected: bool
    tool_calls: list[ToolCallTrace]
    injection_patterns_flagged: list[str]
    handoff: bool
    handoff_reason: str | None
    insufficient_information: bool
    final_response: str
    error: str | None = None
    # Phase 2 additions (Features 16/17): a stable per-turn ID for the
    # trace viewer, and stage-level timing so both the trace viewer and
    # the analytics dashboard's performance section have real numbers to
    # show instead of a single opaque total. All optional/defaulted so
    # every existing caller/trace (including ones already on disk in
    # logs/trace.jsonl) keeps working unchanged.
    trace_id: str = ""
    durations_ms: dict[str, float] = field(default_factory=dict)
    # Provider resilience telemetry. Defaults keep historical trace files
    # backward-compatible while new turns record retry/failover behavior.
    llm_resilience: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class TraceLogger:
    def __init__(self, log_path: Path | None = None):
        # Resolved here (not as a mutable default arg) so it picks up
        # `config.LOG_PATH` at *construction* time rather than at module
        # import time -- this is what lets tests point it at a temp file
        # via monkeypatch without needing every call site to pass a path.
        self._log_path = log_path if log_path is not None else config.LOG_PATH
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, trace: TurnTrace) -> None:
        payload = asdict(trace)
        if config.PII_REDACTION_ENABLED:
            # Phase 3, Feature 22: the trace viewer (Phase 2, Feature 17)
            # must stay useful for debugging retrieval/tool-call behavior,
            # but a customer's raw message or the model's raw reply can
            # contain an email/phone they typed themselves -- redact those
            # two plus conversation history before this ever touches disk,
            # rather than redacting only at display time (so a PII-bearing
            # line is never written even transiently).
            payload["user_message"] = redact_pii(payload["user_message"])
            payload["final_response"] = redact_pii(payload["final_response"])
            payload["history_included"] = redact_pii(payload["history_included"])
            payload["tool_calls"] = redact_pii(payload["tool_calls"])
        # Re-ensure the directory exists on every write, not just at
        # construction time. `self._trace` is a long-lived, process-wide
        # singleton (see app/server.py's get_web_agent()), so anything that
        # can remove the log directory after startup -- a log-rotation/
        # cleanup job, a deploy step, a Docker volume reset, or (as seen in
        # the test suite) a per-test temp directory being torn down between
        # construction and the first actual write -- would otherwise leave
        # every subsequent turn raising FileNotFoundError until the process
        # restarts. mkdir(..., exist_ok=True) is cheap and idempotent, so
        # doing it here is safe to call on every log line.
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, default=str) + "\n"
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except FileNotFoundError:
            # Belt-and-suspenders: the mkdir above can still lose a race
            # against something else removing the directory in the tiny
            # window before open() runs (a per-test tmp dir being torn
            # down, a log-rotation job, antivirus/OS interference on the
            # Temp folder, etc). Recreate the directory and retry once.
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                # Observability must never take down the customer-facing
                # request it's trying to record. If writing the trace
                # line still isn't possible after one retry, log a
                # warning and move on instead of propagating and turning
                # a logging hiccup into a 500 on /conversations/{id}/messages.
                logger.warning(
                    "Failed to write trace log line to %s after retry; dropping it.",
                    self._log_path,
                    exc_info=True,
                )

    def new_trace(self, **kwargs) -> TurnTrace:
        kwargs.setdefault("timestamp", time.time())
        kwargs.setdefault("trace_id", str(uuid.uuid4()))
        return TurnTrace(**kwargs)

    def read_all(self) -> list[dict[str, Any]]:
        if not self._log_path.exists():
            return []
        out = []
        for line in self._log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out
