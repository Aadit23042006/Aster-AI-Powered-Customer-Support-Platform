"""Admin-only Evaluation Dashboard routes (Phase 2, Feature 18)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import require_roles
from app.db.base import get_db
from app.db.models import EvaluationResult, EvaluationRun, User
from app.services import evaluation_service

router = APIRouter(prefix="/admin/evaluations", tags=["evaluations"])

_ADMIN = require_roles("admin", "super_admin")


class RunEvaluationRequest(BaseModel):
    use_mock_llm: bool | None = None
    case_ids: list[str] | None = None


def _run_out(run: EvaluationRun) -> dict:
    return {
        "id": str(run.id),
        "run_number": run.run_number,
        "status": run.status,
        "use_mock_llm": run.use_mock_llm,
        "total_cases": run.total_cases,
        "passed_cases": run.passed_cases,
        "failed_cases": run.failed_cases,
        "category_breakdown": run.category_breakdown,
        "error": run.error,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "created_at": run.created_at,
    }


def _result_out(result: EvaluationResult) -> dict:
    return {
        "id": str(result.id),
        "case_id": result.case_id,
        "category": result.category,
        "passed": result.passed,
        "checks": result.checks,
        "notes": result.notes,
        "answer_preview": result.answer_preview,
    }


@router.get("")
def list_runs(page: int = 1, page_size: int = 25, user: User = Depends(_ADMIN), db: Session = Depends(get_db)) -> dict:
    rows, total = evaluation_service.list_runs(db, page=page, page_size=page_size)
    return {"items": [_run_out(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/run", status_code=202)
def run_evaluation(payload: RunEvaluationRequest, user: User = Depends(_ADMIN), db: Session = Depends(get_db)) -> dict:
    run = evaluation_service.run_evaluation(db, use_mock_llm=payload.use_mock_llm, started_by=user.id, case_ids=payload.case_ids)
    return _run_out(run)


@router.get("/compare")
def compare(run_a: uuid.UUID, run_b: uuid.UUID, user: User = Depends(_ADMIN), db: Session = Depends(get_db)) -> dict:
    try:
        return evaluation_service.compare_runs(db, run_a, run_b)
    except evaluation_service.EvaluationError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{run_id}")
def get_run(run_id: uuid.UUID, user: User = Depends(_ADMIN), db: Session = Depends(get_db)) -> dict:
    run = evaluation_service.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    results = evaluation_service.get_run_results(db, run_id)
    return {**_run_out(run), "results": [_result_out(r) for r in results]}


@router.get("/{run_id}/results/{case_id}")
def get_case_result(run_id: uuid.UUID, case_id: str, user: User = Depends(_ADMIN), db: Session = Depends(get_db)) -> dict:
    results = evaluation_service.get_run_results(db, run_id)
    for r in results:
        if r.case_id == case_id:
            return _result_out(r)
    raise HTTPException(status_code=404, detail="Test case result not found in this run.")
