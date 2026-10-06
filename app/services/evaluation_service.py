"""Feature 18: Evaluation Dashboard.

Wraps the existing `evaluation/run_eval.py` harness (its `run_all` and
`summarize` functions, and its two case files) unchanged -- this module
just persists what that harness already computes into
`EvaluationRun`/`EvaluationResult` rows so an admin can trigger and browse
runs from the web UI instead of only the CLI. No evaluation logic is
duplicated here.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import config
from app.db.models import EvaluationResult, EvaluationRun

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class EvaluationError(Exception):
    pass


def _load_cases(case_ids: list[str] | None) -> list[dict]:
    eval_dir = _REPO_ROOT / "evaluation"
    visible = json.loads((eval_dir / "visible-cases.json").read_text(encoding="utf-8"))["cases"]
    custom = json.loads((eval_dir / "custom-cases.json").read_text(encoding="utf-8"))["cases"]
    cases = visible + custom
    if case_ids:
        cases = [c for c in cases if c["id"] in case_ids]
    return cases


def _next_run_number(db: Session) -> int:
    return (db.query(func.max(EvaluationRun.run_number)).scalar() or 0) + 1


def run_evaluation(
    db: Session,
    *,
    use_mock_llm: bool | None,
    started_by: uuid.UUID,
    case_ids: list[str] | None = None,
) -> EvaluationRun:
    """Runs the harness synchronously (see the note on `kb_routes.py`'s
    `_reindex_after_status_change` for why: a deferred FastAPI
    BackgroundTask can never be reflected in the response that scheduled
    it) and persists the result. Defaults to the harness's own mock/real
    resolution (`config.USE_MOCK_LLM`, i.e. real Gemini unless
    USE_MOCK_LLM=1 is set) when `use_mock_llm` isn't given explicitly."""
    from evaluation.run_eval import run_all, summarize  # local import: keeps the eval harness's own
    from app.bootstrap import build_agent  # sys.path.insert above makes the `evaluation` package importable

    resolved_mock = config.USE_MOCK_LLM if use_mock_llm is None else use_mock_llm

    run = EvaluationRun(
        run_number=_next_run_number(db),
        status="running",
        use_mock_llm=resolved_mock,
        started_by=started_by,
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        cases = _load_cases(case_ids)
        if not cases:
            raise EvaluationError("No matching evaluation cases found.")
        agent = build_agent(use_mock_llm=resolved_mock)
        results = run_all(agent, cases)
        summary = summarize(results)

        for case_result in summary["cases"]:
            db.add(
                EvaluationResult(
                    run_id=run.id,
                    case_id=case_result["id"],
                    category=case_result["category"],
                    passed=case_result["passed"],
                    checks=case_result["checks"],
                    notes=case_result["notes"],
                    answer_preview=case_result["answer_preview"],
                )
            )

        run.status = "completed"
        run.total_cases = summary["overall"]["total"]
        run.passed_cases = summary["overall"]["passed"]
        run.failed_cases = run.total_cases - run.passed_cases
        run.category_breakdown = summary["by_category"]
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - a failed run must be recorded, not crash the request
        db.rollback()
        run = db.get(EvaluationRun, run.id)
        run.status = "failed"
        run.error = str(exc)[:2000]
        run.completed_at = datetime.now(timezone.utc)
        db.commit()

    db.refresh(run)
    return run


def list_runs(db: Session, *, page: int = 1, page_size: int = 25) -> tuple[list[EvaluationRun], int]:
    page_size = min(max(page_size, 1), 100)
    query = db.query(EvaluationRun).order_by(EvaluationRun.run_number.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def get_run(db: Session, run_id: uuid.UUID) -> EvaluationRun | None:
    return db.get(EvaluationRun, run_id)


def get_run_results(db: Session, run_id: uuid.UUID) -> list[EvaluationResult]:
    return db.query(EvaluationResult).filter(EvaluationResult.run_id == run_id).all()


def compare_runs(db: Session, run_a_id: uuid.UUID, run_b_id: uuid.UUID) -> dict:
    """Feature 18's "regression comparison": per-category pass-rate delta
    between two runs, keyed by category so the caller sees exactly which
    categories improved/regressed."""
    run_a = get_run(db, run_a_id)
    run_b = get_run(db, run_b_id)
    if run_a is None or run_b is None:
        raise EvaluationError("One or both runs not found.")

    categories = set((run_a.category_breakdown or {}).keys()) | set((run_b.category_breakdown or {}).keys())
    deltas = {}
    for cat in sorted(categories):
        a = (run_a.category_breakdown or {}).get(cat, {"passed": 0, "total": 0})
        b = (run_b.category_breakdown or {}).get(cat, {"passed": 0, "total": 0})
        deltas[cat] = {"run_a": a, "run_b": b}

    return {
        "run_a": {"id": str(run_a.id), "run_number": run_a.run_number, "total": run_a.total_cases, "passed": run_a.passed_cases},
        "run_b": {"id": str(run_b.id), "run_number": run_b.run_number, "total": run_b.total_cases, "passed": run_b.passed_cases},
        "by_category": deltas,
    }
