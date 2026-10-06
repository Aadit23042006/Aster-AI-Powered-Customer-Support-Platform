"""Defense-in-depth helpers for treating retrieved/tool content as untrusted
data rather than instructions.

The primary defense is architectural, not textual:
- The model never sees the raw orders.json (app/orders.py field-filters it).
- Retrieved KB passages are wrapped in explicit, clearly-labelled delimiters
  and the system prompt states in multiple ways that anything inside those
  delimiters is reference material, never a command.
- Operational/agent-config docs (escalation rules) come from the repo's own
  system prompt, not from a retrieval call over content someone else could
  edit later -- see kb_loader.AGENT_POLICY_FILES.

This module adds a *secondary* backstop on top of that: pattern-based
flagging (for the trace log / tests) and a forbidden-field scrub that runs
on every tool result and every retrieved chunk before it's logged or shown,
independent of whether the LLM behaved correctly.
"""
from __future__ import annotations

import re

_INJECTION_PATTERNS = [
    re.compile(r"system\s+instruction", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?(prior|previous|above)\s+(rules|instructions)", re.IGNORECASE),
    re.compile(r"reveal\s+(your|the)\s+(hidden\s+)?(prompt|instructions)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
    re.compile(r"disregard\s+(your|the)\s+(guidelines|rules|instructions)", re.IGNORECASE),
]

# Fields that must never appear in anything shown to the customer or logged
# in the "final response" trace field, as a last-resort scrub in case a
# future data source accidentally included them. app/orders.py already
# excludes these at the source; this is the belt-and-suspenders check.
FORBIDDEN_FIELD_MARKERS = [
    "risk_score",
    "risk score",
    "warehouse_note",
    "shipping_address",
    "@example.test",  # every mock customer email in orders.json uses this domain
]


def flag_injection_patterns(text: str) -> list[str]:
    """Returns the list of suspicious pattern names found in `text`, purely
    for observability (trace log) and unit testing. This is NOT what makes
    the agent safe -- the system prompt + architecture do that -- it's how
    we can assert in tests that a known payload was in fact detected."""
    hits = []
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            hits.append(pattern.pattern)
    return hits


def wrap_untrusted(label: str, text: str) -> str:
    """Wrap a piece of retrieved/tool content in an explicit delimiter block
    so it's unambiguous in the prompt where untrusted data starts/ends."""
    return f"<untrusted_{label}>\n{text}\n</untrusted_{label}>"


def contains_forbidden_field(text: str) -> str | None:
    lowered = text.lower()
    for marker in FORBIDDEN_FIELD_MARKERS:
        if marker.lower() in lowered:
            return marker
    return None
