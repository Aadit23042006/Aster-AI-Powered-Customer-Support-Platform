from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.api.web_schemas import UpdateProfileRequest, UserOut
from app.db.base import get_db
from app.db.models import User

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, roles=sorted(user.role_names), created_at=user.created_at)


@router.patch("/me", response_model=UserOut)
def update_me(payload: UpdateProfileRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserOut:
    if payload.full_name:
        user.full_name = payload.full_name.strip()
    db.commit()
    db.refresh(user)
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, roles=sorted(user.role_names), created_at=user.created_at)
