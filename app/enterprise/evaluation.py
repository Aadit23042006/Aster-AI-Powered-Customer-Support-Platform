"""AI Evaluation Playground engine.

Isolation: nothing here writes conversations/messages/tickets. An evaluation
uses a throw-away agent session id and only persists EvaluationPlaygroundRun
rows.

Metrics are LEXICAL PROXIES (evaluator "lexical-v1"), not LLM-judged scores:
  groundedness     share of the answer's content words found in retrieved passages
  answer_relevance recall of the expected answer's words (if given), else
                   coverage of the question's words by the answer
  faithfulness     share of numbers in the answer that appear in the evidence
                   (None when the answer has no numbers to verify)
"""
from __future__ import annotations

import re
import time
import uuid

from app import config
from app.enterprise.quality import _content_tokens, _strip_footer, evidence_scores
from app.llm_usage import UsageCollector, model_override_var, usage_collector_var

EVALUATOR_VERSION = "lexical-v1"
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def compute_metrics(question: str, answer: str, expected: str | None, evidence: list[str],
                    retrieval_score: float | None = None) -> dict:
    grounded = None
    if evidence and answer:
        grounded, _rel = evidence_scores(answer, question, evidence, None)
    ans_tokens = _content_tokens(_strip_footer(answer))
    if expected and expected.strip():
        exp = _content_tokens(expected)
        relevance = round(len(exp & ans_tokens) / len(exp), 4) if exp else None
    else:
        q = _content_tokens(question)
        relevance = round(len(q & ans_tokens) / len(q), 4) if q and ans_tokens else None
    nums = set(_NUM.findall(answer or ""))
    ev_text = " ".join(evidence)
    faithfulness = round(sum(1 for n in nums if n in ev_text) / len(nums), 4) if nums and evidence else None
    return {"groundedness": grounded, "answer_relevance": relevance, "faithfulness": faithfulness,
            "retrieval_count": len(evidence), "retrieval_score": retrieval_score}


def run_case(agent, question: str, expected: str | None = None, *, model: str | None = None,
             prompt_text: str | None = None, top_k: int | None = None, generate: bool = True) -> dict:
    """Runs one isolated evaluation and returns answer/sources/metrics/latency/tokens."""
    collector = UsageCollector()
    ctok = usage_collector_var.set(collector)
    mtok = model_override_var.set(model) if model and model != config.CHAT_MODEL else None
    started = time.perf_counter()
    answer, error, sources = "", None, []
    evidence: list[str] = []
    best = None
    try:
        retrieval = agent.retriever.retrieve(question, top_k=top_k)
        sources = [{"source_file": h.chunk.source_file, "heading": getattr(h.chunk, "heading", None),
                    "chunk_id": getattr(h.chunk, "chunk_id", None), "score": round(float(h.score), 4)} for h in retrieval.hits][:15]
        evidence = [h.chunk.text for h in retrieval.hits]
        best = max((float(h.score) for h in retrieval.hits), default=None)
        if generate:
            if prompt_text is not None:
                # Compare Prompts: same retrieval, candidate prompt as the system instruction.
                block = "\n\n".join(f"[source_file: {h.chunk.source_file}]\n{h.chunk.text}" for h in retrieval.hits)
                contents = [{"role": "system_context", "text": block}, {"role": "user", "text": question}]
                ans = agent._llm.generate_structured_answer(prompt_text, contents)
                answer = ans.answer
            else:
                answer = agent.handle_turn(f"playground-{uuid.uuid4()}", question).answer
    except Exception:  # noqa: BLE001
        error = "Evaluation could not be completed."
    finally:
        if mtok is not None:
            model_override_var.reset(mtok)
        usage_collector_var.reset(ctok)
    latency = (time.perf_counter() - started) * 1000
    metrics = compute_metrics(question, answer, expected, evidence, best) if generate else \
        {"groundedness": None, "answer_relevance": None, "faithfulness": None, "retrieval_count": len(evidence), "retrieval_score": best}
    metrics["latency_ms"] = round(latency, 2)
    return {"answer": answer, "sources": sources, "metrics": metrics, "latency_ms": latency, "error": error,
            "token_usage": {"input_tokens": collector.input_tokens, "output_tokens": collector.output_tokens,
                            "total_tokens": collector.total_tokens},
            "model_used": collector.models[0] if collector.models else (model or config.CHAT_MODEL)}
