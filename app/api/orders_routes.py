from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.api.web_schemas import OrderOut
from app.db.base import get_db
from app.db.models import OrganizationMember, Order, User
from app.phase4 import get_current_org
from app.services.order_service import get_order_for_user, list_orders_for_user

router = APIRouter(prefix="/orders", tags=["orders"])


_STAFF_ROLES = {
    "support_agent",
    "admin",
    "super_admin",
}


@router.get("", response_model=list[OrderOut])
def list_orders(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[OrderOut]:
    return list_orders_for_user(db, user.id)


@router.get("/{order_id}", response_model=OrderOut)
def get_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
) -> OrderOut:

    # Customers may only access their own orders.
    if not (user.role_names & _STAFF_ROLES):
        order = get_order_for_user(db, user.id, order_id)

        if order is None:
            raise HTTPException(
                status_code=404,
                detail="Order not found.",
            )

        return order

    # Staff may access orders belonging to users in their
    # active organization.
    allowed_user_ids = [
        member.user_id
        for member in (
            db.query(OrganizationMember)
            .filter(
                OrganizationMember.organization_id == org.id,
                OrganizationMember.status == "active",
            )
            .all()
        )
    ]

    order = (
        db.query(Order)
        .filter(
            Order.id == order_id,
            Order.user_id.in_(allowed_user_ids),
        )
        .first()
    )

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found.",
        )

    return order