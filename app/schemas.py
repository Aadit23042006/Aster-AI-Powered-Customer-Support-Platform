from __future__ import annotations

from pydantic import BaseModel, Field


class AgentAnswer(BaseModel):
    """The model's structured final answer for a turn. The backend still
    applies deterministic overrides (see agent.py `_apply_deterministic_handoff_rules`)
    on top of `handoff_recommended` / `insufficient_information` -- these
    fields are the model's own judgment, not the last word."""

    answer: str = Field(description="The natural-language reply to show the customer. Do not include a sources list in here -- that is rendered separately.")
    cited_document_ids: list[str] = Field(
        default_factory=list,
        description="Filenames (e.g. '01-returns-policy-current.md') of the retrieved documents this answer actually relies on. Only include documents that were provided to you as reference material.",
    )
    insufficient_information: bool = Field(
        description="True if the supplied knowledge base / order data does not contain enough information to answer reliably."
    )
    handoff_recommended: bool = Field(
        description="True if a human support specialist should be looped in (per the escalation rules you were given)."
    )
    handoff_reason: str | None = Field(
        default=None, description="One short sentence on why a handoff is recommended, or null if handoff_recommended is false."
    )
