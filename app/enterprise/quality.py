from __future__ import annotations

import re
from dataclasses import dataclass, field

from app import config
from app.security.pii import redact_pii


# ---------------------------------------------------------------------------
# Tokenization / grounding helpers
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9][a-z0-9'-]{3,}")

_STOP = {
    "this",
    "that",
    "with",
    "from",
    "have",
    "your",
    "what",
    "will",
    "about",
    "would",
    "could",
    "there",
    "their",
    "which",
    "when",
    "where",
    "then",
    "than",
    "them",
    "they",
    "were",
    "been",
    "also",
    "into",
    "please",
    "thanks",
    "thank",
    "happy",
    "help",
    "here",
    "some",
    "just",
    "based",
    "policy",
    "documentation",
    "source",
    "sources",
    "source_file",
    "active",
    "official",
    "authoritative",
}


# ---------------------------------------------------------------------------
# Safe fallback text
# ---------------------------------------------------------------------------

CLARIFICATION_TEXT = (
    "I want to make sure I give you accurate information. "
    "Could you share a few more details about what you need "
    "(for example the product, order number, or situation)?"
)


# ---------------------------------------------------------------------------
# Quality result
# ---------------------------------------------------------------------------

@dataclass
class QualityResult:
    grounding_score: float
    policy_check: str
    pii_check: str
    confidence: str
    decision: str
    retrieval_score: float | None = None
    relevance_score: float | None = None
    fallback_action: str | None = None
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _content_tokens(text: str) -> set[str]:
    """
    Extract meaningful content tokens from text.

    Short words and common conversational / documentation terms are
    intentionally excluded so grounding is based on substantive overlap.
    """
    return {
        word
        for word in _WORD.findall((text or "").lower())
        if word not in _STOP
    }


def _strip_footer(answer: str) -> str:
    """
    Remove citation/source footer lines before calculating answer grounding.

    Example:
        Sources:
        - policy.pdf

    should not affect the grounding score.
    """
    return "\n".join(
        line
        for line in (answer or "").splitlines()
        if not line.strip().lower().startswith("sources")
    )


# ---------------------------------------------------------------------------
# Evidence / grounding
# ---------------------------------------------------------------------------

def evidence_scores(
    answer: str,
    question: str,
    evidence: list[str],
    retrieval_score: float | None,
) -> tuple[float, float]:
    """
    Calculate:

        grounding_score
        relevance_score

    Grounding is based on passages that were actually retrieved.

    support:
        Share of the answer's meaningful content words found in evidence.

    relevance:
        Share of the question's meaningful content words covered by evidence.

    retrieval_score:
        Retriever confidence normalized against 0.6.

    The final grounding score combines:
        70% answer/evidence support
        30% retrieval quality
    """

    ev_tokens: set[str] = set()

    for text in evidence:
        ev_tokens |= _content_tokens(text)

    answer_tokens = _content_tokens(
        _strip_footer(answer)
    )

    if not evidence or not ev_tokens:
        return 0.0, 0.0

    support = (
        len(answer_tokens & ev_tokens) / len(answer_tokens)
        if answer_tokens
        else 1.0
    )

    question_tokens = _content_tokens(question)

    relevance = (
        len(question_tokens & ev_tokens) / len(question_tokens)
        if question_tokens
        else 1.0
    )

    if retrieval_score is None:
        retrieval_quality = support
    else:
        retrieval_quality = min(
            1.0,
            max(
                0.0,
                retrieval_score,
            )
            / 0.6,
        )

    grounding = (
        0.7 * support
        + 0.3 * retrieval_quality
    )

    return (
        round(min(1.0, grounding), 4),
        round(relevance, 4),
    )


# ---------------------------------------------------------------------------
# Quality assessment
# ---------------------------------------------------------------------------

def assess(
    answer: str,
    sources: list[str],
    handoff: bool = False,
    eligible: bool = True,
    *,
    question: str = "",
    evidence: list[str] | None = None,
    retrieval_score: float | None = None,
    allow_general_knowledge: bool = False,
) -> QualityResult:
    """
    Perform the Quality Guard decision before the response is returned.

    Decision priority is intentionally:

        1. BLOCK
        2. HUMAN_HANDOFF
        3. ALLOW
        4. RETRY_RETRIEVAL

    The BLOCK priority is critical.

    An unsafe LLM response must NEVER be allowed through merely because
    the model or deterministic rules also requested a human handoff.

    Configuration is controlled through:

        QUALITY_GROUNDING_ALLOW
        QUALITY_GROUNDING_HIGH
        QUALITY_GROUNDING_MEDIUM

    When evidence is supplied, grounding is calculated from the passages
    actually retrieved.

    When evidence is not supplied, the legacy source-presence heuristic
    remains available for backward compatibility.
    """

    # -----------------------------------------------------------------------
    # Guard disabled / ineligible
    # -----------------------------------------------------------------------

    if not eligible:
        return QualityResult(
            grounding_score=1.0,
            policy_check="PASS",
            pii_check="PASS",
            confidence="HIGH",
            decision="ALLOW",
        )

    # -----------------------------------------------------------------------
    # Grounding / relevance
    # -----------------------------------------------------------------------

    relevance: float | None = None

    if evidence is not None:
        grounded, relevance = evidence_scores(
            answer=answer,
            question=question,
            evidence=evidence,
            retrieval_score=retrieval_score,
        )
    else:
        # Backward-compatible heuristic:
        # an answer with authoritative sources gets a high provisional score;
        # an answer without sources gets a lower score.
        grounded = (
            0.95
            if sources
            else 0.55
        )

    # -----------------------------------------------------------------------
    # Policy safety check
    # -----------------------------------------------------------------------

    # These patterns represent content that must not be exposed to customers.
    #
    # IMPORTANT:
    # This check is performed independently of handoff state.
    # A response containing one of these patterns must be BLOCKED.
    policy = (
        "PASS"
        if not re.search(
            r"(system prompt|hidden instructions|password|api key|secret)",
            answer,
            re.I,
        )
        else "FAIL"
    )

    # -----------------------------------------------------------------------
    # PII check
    # -----------------------------------------------------------------------

    pii = (
        "PASS"
        if redact_pii(answer) == answer
        else "WARN"
    )

    # -----------------------------------------------------------------------
    # Confidence
    # -----------------------------------------------------------------------

    if grounded >= config.QUALITY_GROUNDING_HIGH:
        confidence = "HIGH"
    elif grounded >= config.QUALITY_GROUNDING_MEDIUM:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # -----------------------------------------------------------------------
    # Final decision
    # -----------------------------------------------------------------------

    # SAFETY FIRST:
    #
    # Policy/PII violations MUST take priority over HUMAN_HANDOFF.
    #
    # Example:
    #
    #   unsafe LLM answer
    #        +
    #   insufficient_information=True
    #
    # The Agent may convert that into handoff=True.
    #
    # The Quality Guard must STILL return BLOCK because the generated
    # content itself is unsafe.
    #
    # Otherwise an unsafe response could accidentally reach the customer
    # simply because the model also requested human handoff.
    if policy == "FAIL" or pii == "WARN":
        decision = "BLOCK"

    elif handoff:
        decision = "HUMAN_HANDOFF"

    elif allow_general_knowledge:
        # General knowledge is intentionally not grounded in the Aster & Row
        # KB. Policy and PII checks above still apply.
        decision = "ALLOW"

    elif grounded >= config.QUALITY_GROUNDING_ALLOW:
        decision = "ALLOW"

    else:
        decision = "RETRY_RETRIEVAL"

    # -----------------------------------------------------------------------
    # Result
    # -----------------------------------------------------------------------

    return QualityResult(
        grounding_score=grounded,
        policy_check=policy,
        pii_check=pii,
        confidence=confidence,
        decision=decision,
        retrieval_score=retrieval_score,
        relevance_score=relevance,
        details={
            "thresholds": {
                "allow": config.QUALITY_GROUNDING_ALLOW,
                "high": config.QUALITY_GROUNDING_HIGH,
                "medium": config.QUALITY_GROUNDING_MEDIUM,
            }
        },
    )


# ---------------------------------------------------------------------------
# Clarification helper
# ---------------------------------------------------------------------------

def needs_clarification(
    user_message: str,
) -> bool:
    """
    Determine whether the user message is short enough that the Quality Guard
    should prefer a clarification response after unsuccessful retrieval.
    """

    return (
        len(
            (user_message or "").split()
        )
        <= config.QUALITY_CLARIFY_MAX_WORDS
    )
