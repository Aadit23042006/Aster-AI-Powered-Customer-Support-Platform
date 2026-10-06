#!/usr/bin/env python3
"""Evaluation harness.

    python evaluation/run_eval.py                       # real Gemini API (needs GEMINI_API_KEY)
    python evaluation/run_eval.py --mock                 # offline demo mode, no API key/network
    python evaluation/run_eval.py --out results/final.json

Loads evaluation/visible-cases.json (supplied) and evaluation/custom-cases.json
(this project's own >=5 additional cases), runs each case's messages in a
single session, and checks the final turn's result against the case's
`expect` block.

Design choices, per the assignment's evaluation-suite requirements:

* Deterministic assertions wherever practical: `must_include` /
  `must_not_include` are literal case-insensitive substring checks;
  `required_sources` / `forbidden_sources_as_authority` check the exact
  citation footer the app rendered (not the model's prose); `tool` /
  `tool_arguments` check the actual trace of tool calls the agent made;
  `handoff` checks the agent's final (deterministic-rule-adjusted) handoff
  decision. None of these ask another LLM to grade anything.
* `must_include_concepts` / `must_not_follow` cannot be exact-string
  matched (the supplied cases explicitly say exact wording isn't required),
  so they use per-concept curated keyword-group patterns
  (`evaluation/concepts.py`) where one exists for that exact concept string,
  falling back to a generic majority-of-distinctive-keywords heuristic
  otherwise. Neither path asks another LLM to grade anything, but both are
  intentionally coarse -- a smoke check, not a substitute for a human
  skimming the trace log for the handful of concept cases. That trade-off,
  and why, is called out again in the README.
* `must_not_invent` is verified indirectly through the `tool` expectation
  (see `_check_tool`) rather than scanning for an open-ended set of
  "invented-sounding" values, which isn't a deterministic check.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bootstrap import build_agent  # noqa: E402
from evaluation.concepts import concept_satisfied  # noqa: E402

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "to", "of", "and", "or", "in",
    "on", "for", "with", "that", "this", "it", "its", "as", "at", "by", "from", "not", "does",
    "do", "did", "has", "have", "had", "will", "would", "should", "can", "cannot", "must", "one",
}


def _keywords(phrase: str) -> list[str]:
    words = re.findall(r"[a-z0-9%$-]+", phrase.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 1]


def _concept_present(concept: str, answer: str) -> bool:
    kws = _keywords(concept)
    if not kws:
        return True
    answer_lower = answer.lower()
    hits = sum(1 for kw in kws if kw in answer_lower)
    return hits / len(kws) >= 0.6  # majority of distinctive terms present


@dataclass
class CaseResult:
    case_id: str
    category: str
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    answer_preview: str = ""


def _check_must_include(expect: dict, result, notes: list[str]) -> bool:
    ok = True
    for phrase in expect.get("must_include", []):
        if phrase.lower() not in result.answer.lower():
            ok = False
            notes.append(f"missing required phrase: {phrase!r}")
    return ok


def _check_must_not_include(expect: dict, result, notes: list[str]) -> bool:
    ok = True
    for phrase in expect.get("must_not_include", []):
        if phrase.lower() in result.answer.lower():
            ok = False
            notes.append(f"forbidden phrase present: {phrase!r}")
    return ok


def _concept_check(concept: str, answer: str) -> tuple[bool, str]:
    """Prefer the curated per-concept keyword-group patterns in
    evaluation/concepts.py (precise, written per known concept string); fall
    back to the generic majority-of-keywords heuristic for concepts that
    aren't in that curated set (e.g. this project's own custom-cases.json
    concepts not already covered there). Returns (satisfied, method_label)."""
    curated = concept_satisfied(concept, answer)
    if curated is not None:
        return curated, "curated pattern"
    return _concept_present(concept, answer), "generic keyword heuristic"


def _check_concepts(expect: dict, result, notes: list[str]) -> bool:
    ok = True
    for concept in expect.get("must_include_concepts", []):
        satisfied, method = _concept_check(concept, result.answer)
        if not satisfied:
            ok = False
            notes.append(f"concept not clearly covered ({method}): {concept!r}")
    for concept in expect.get("must_not_follow", []):
        satisfied, method = _concept_check(concept, result.answer)
        if satisfied:
            ok = False
            notes.append(f"looks like a forbidden concept was followed ({method}): {concept!r}")
    return ok


def _check_sources(expect: dict, result, notes: list[str]) -> bool:
    ok = True
    for src in expect.get("required_sources", []):
        if src not in result.sources:
            ok = False
            notes.append(f"missing required source in citation footer: {src}")
    for src in expect.get("forbidden_sources_as_authority", []):
        if src in result.sources:
            ok = False
            notes.append(f"forbidden source cited as authority: {src}")
    if expect.get("must_not_silently_choose_one") and len(expect.get("required_sources", [])) >= 2:
        present = [s for s in expect["required_sources"] if s in result.sources]
        if len(present) < 2:
            ok = False
            notes.append("expected both conflicting sources to be cited (not silently picking one)")
    return ok


def _check_tool(expect: dict, trace: dict, notes: list[str]) -> bool:
    tool_calls = trace.get("tool_calls", [])
    expectation = expect.get("tool")
    if expectation is None:
        return True
    if expectation == "not_called":
        ok = len(tool_calls) == 0
        if not ok:
            notes.append("expected no tool call, but one was made")
        return ok
    if expectation == "order_lookup":
        ok = any(tc["name"] == "order_lookup" and tc["result"].get("found") for tc in tool_calls)
        if not ok:
            notes.append("expected a successful order_lookup call")
        args = expect.get("tool_arguments")
        if ok and args:
            called_with = next(tc["arguments"] for tc in tool_calls if tc["name"] == "order_lookup")
            for k, v in args.items():
                if str(called_with.get(k, "")).upper() != str(v).upper():
                    ok = False
                    notes.append(f"tool_arguments mismatch on {k}: expected {v!r}, got {called_with.get(k)!r}")
        return ok
    if expectation == "not_called_without_id":
        ok = all(tc["result"].get("found") is not True for tc in tool_calls)
        if not ok:
            notes.append("a real order lookup happened despite no id having been given")
        return ok
    if expectation == "optional_sanitized_lookup":
        for tc in tool_calls:
            for forbidden in ("email", "shipping_address", "internal", "risk_score", "warehouse_note"):
                if forbidden in json.dumps(tc.get("result", {})):
                    notes.append(f"tool result contained forbidden field: {forbidden}")
                    return False
        return True
    notes.append(f"unknown tool expectation: {expectation!r}")
    return False


def _check_ask_for(expect: dict, result, notes: list[str]) -> bool:
    targets = expect.get("must_ask_for", [])
    if not targets:
        return True
    ok = True
    for target in targets:
        if not _concept_present(f"ask for {target}", result.answer) and target.lower() not in result.answer.lower():
            ok = False
            notes.append(f"expected the agent to ask for: {target}")
    return ok


def _check_handoff(expect: dict, result, notes: list[str]) -> bool:
    if "handoff" not in expect:
        return True
    ok = result.handoff == expect["handoff"]
    if not ok:
        notes.append(f"handoff mismatch: expected {expect['handoff']}, got {result.handoff} ({result.handoff_reason})")
    return ok


def run_case(agent, case: dict) -> CaseResult:
    session_id = f"eval::{case['id']}"
    result = None
    for msg in case["messages"]:
        if msg["role"] != "user":
            continue
        result = agent.handle_turn(session_id, msg["content"])
    trace = agent._trace.read_all()[-1]  # noqa: SLF001 - the harness is allowed to reach into internals

    expect = case["expect"]
    notes: list[str] = []
    checks = {
        "must_include": _check_must_include(expect, result, notes),
        "must_not_include": _check_must_not_include(expect, result, notes),
        "concepts": _check_concepts(expect, result, notes),
        "sources": _check_sources(expect, result, notes),
        "tool": _check_tool(expect, trace, notes),
        "must_ask_for": _check_ask_for(expect, result, notes),
        "handoff": _check_handoff(expect, result, notes),
    }
    passed = all(checks.values())
    return CaseResult(
        case_id=case["id"], category=case["category"], passed=passed, checks=checks,
        notes=notes, answer_preview=result.answer[:200],
    )


def run_all(agent, cases: list[dict]) -> list[CaseResult]:
    out = []
    for case in cases:
        try:
            out.append(run_case(agent, case))
        except Exception as exc:  # noqa: BLE001 - a crashed case is a failed case, not a harness crash
            out.append(CaseResult(case_id=case["id"], category=case.get("category", "unknown"), passed=False,
                                   notes=[f"CRASHED: {exc!r}"]))
    return out


def summarize(results: list[CaseResult]) -> dict:
    by_category = defaultdict(lambda: {"passed": 0, "total": 0})
    for r in results:
        by_category[r.category]["total"] += 1
        by_category[r.category]["passed"] += int(r.passed)
    overall_passed = sum(r.passed for r in results)
    return {
        "overall": {"passed": overall_passed, "total": len(results), "pass_rate": round(overall_passed / len(results), 3) if results else None},
        "by_category": dict(by_category),
        "cases": [
            {"id": r.case_id, "category": r.category, "passed": r.passed, "checks": r.checks, "notes": r.notes, "answer_preview": r.answer_preview}
            for r in results
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="Use the offline mock LLM instead of the real Gemini API.")
    parser.add_argument("--out", default=None, help="Write the JSON report to this path in addition to stdout.")
    parser.add_argument("--cases", nargs="*", default=None, help="Restrict to specific case ids.")
    args = parser.parse_args()

    here = Path(__file__).resolve().parent
    visible = json.loads((here / "visible-cases.json").read_text(encoding="utf-8"))["cases"]
    custom = json.loads((here / "custom-cases.json").read_text(encoding="utf-8"))["cases"]
    cases = visible + custom
    if args.cases:
        cases = [c for c in cases if c["id"] in args.cases]

    agent = build_agent(use_mock_llm=args.mock)
    results = run_all(agent, cases)
    summary = summarize(results)

    print(json.dumps(summary["overall"], indent=2))
    print("\nBy category:")
    for cat, stats in sorted(summary["by_category"].items()):
        print(f"  {cat:28s} {stats['passed']}/{stats['total']}")
    print("\nFailures:")
    any_failure = False
    for c in summary["cases"]:
        if not c["passed"]:
            any_failure = True
            print(f"  [{c['category']}] {c['id']}")
            for n in c["notes"]:
                print(f"      - {n}")
    if not any_failure:
        print("  (none)")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\nWrote full report to {out_path}")


if __name__ == "__main__":
    main()
