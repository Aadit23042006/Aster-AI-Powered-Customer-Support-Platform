"""In-memory, per-session conversation history.

Deliberately not a database: the assignment explicitly says not to build
production infra. Each session_id maps to a bounded list of turns. Sessions
idle past SESSION_TTL_SECONDS are dropped on next access so one customer's
history can never leak into another session, and the process doesn't grow
unboundedly in a long-running demo.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from app import config


@dataclass
class Turn:
    role: str  # "user" | "assistant"
    content: str
    # last order_id successfully looked up in this turn, if any -- lets a
    # bare follow-up like "when will it arrive?" resolve without repeating
    # the order id.
    order_id: str | None = None

    @property
    def role_for_llm(self) -> str:
        """Gemini's Content.role uses 'model' rather than 'assistant'."""
        return "model" if self.role == "assistant" else self.role


@dataclass
class Session:
    session_id: str
    turns: list[Turn] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)
    last_order_id: str | None = None

    def add(self, role: str, content: str, order_id: str | None = None) -> None:
        self.turns.append(Turn(role=role, content=content, order_id=order_id))
        self.last_active = time.time()
        if order_id:
            self.last_order_id = order_id

    def recent_turns(self, max_turns: int = config.MAX_HISTORY_TURNS) -> list[Turn]:
        return self.turns[-max_turns:]


class SessionStore:
    def __init__(self, ttl_seconds: int = config.SESSION_TTL_SECONDS):
        self._sessions: dict[str, Session] = {}
        self._ttl = ttl_seconds

    def get_or_create(self, session_id: str) -> Session:
        self._evict_expired()
        if session_id not in self._sessions:
            self._sessions[session_id] = Session(session_id=session_id)
        return self._sessions[session_id]

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if now - s.last_active > self._ttl]
        for sid in expired:
            del self._sessions[sid]

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
