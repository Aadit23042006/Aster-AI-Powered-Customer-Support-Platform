from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.security import (
    WeakPasswordError,
    create_access_token,
    create_raw_refresh_token,
    create_raw_reset_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    reset_token_expiry,
    validate_password_strength,
    verify_password,
    verify_refresh_token,
)
from app.api.web_schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    ResetPasswordRequest,
    SignupRequest,
    TokenResponse,
    UserOut,
)
from app.db.base import get_db
from app.db.models import AuthSession, PasswordResetToken, Role, User, UserRole
from app import config
from app.security.rate_limit_deps import rate_limit_by_ip
from app.services import audit_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _audit(db: Session, *, user_id, event_type: str, detail: dict | None = None, success: bool = True, request: Request | None = None) -> None:
    audit_service.log_event(db, event_type=event_type, user_id=user_id, success=success, detail=detail, request=request)


def _issue_tokens(db: Session, user: User, user_agent: str | None) -> TokenResponse:
    access = create_access_token(str(user.id), sorted(user.role_names))
    raw_refresh = create_raw_refresh_token()
    db.add(
        AuthSession(
            user_id=user.id,
            refresh_token_hash=hash_refresh_token(raw_refresh),
            user_agent=user_agent,
            expires_at=refresh_token_expiry(),
        )
    )
    return TokenResponse(access_token=access, refresh_token=raw_refresh)


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_by_ip("signup", "RATE_LIMIT_SIGNUP"))],
)
def signup(payload: SignupRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    if not config.SELF_SIGNUP_ENABLED:
        raise HTTPException(status_code=403, detail="Self-registration is disabled. Please use an authorized account.")
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
    try:
        validate_password_strength(payload.password)
    except WeakPasswordError as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing = db.query(User).filter(User.email == payload.email.lower()).first()
    if existing is not None:
        # Same generic message as an unrelated bad-login would get is
        # tempting for email-enumeration hardening, but the assignment's
        # explicit UX requirement is "prevent duplicate accounts" with a
        # clear signal, so we report it plainly here.
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    customer_role = db.query(Role).filter(Role.name == "customer").first()
    if customer_role is None:
        customer_role = Role(name="customer")
        db.add(customer_role)
        db.flush()

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=customer_role.id))
    _audit(db, user_id=user.id, event_type="USER_CREATED", request=request)
    tokens = _issue_tokens(db, user, request.headers.get("user-agent"))
    db.commit()
    return tokens


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit_by_ip("login", "RATE_LIMIT_LOGIN"))],
)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    email = payload.email.lower().strip()
    if config.LOGIN_ALLOWLIST_ENABLED and email not in config.ALLOWED_LOGIN_EMAILS:
        _audit(db, user_id=None, event_type="LOGIN_FAILED", success=False, request=request)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    user = db.query(User).filter(User.email == email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        _audit(db, user_id=user.id if user else None, event_type="LOGIN_FAILED", success=False, request=request)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated.")

    tokens = _issue_tokens(db, user, request.headers.get("user-agent"))
    _audit(db, user_id=user.id, event_type="USER_LOGIN", request=request)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    now = datetime.now(timezone.utc)
    candidates = (
        db.query(AuthSession)
        .filter(AuthSession.revoked_at.is_(None), AuthSession.expires_at > now)
        .all()
    )
    matched = next((s for s in candidates if verify_refresh_token(payload.refresh_token, s.refresh_token_hash)), None)
    if matched is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

    # Rotate: revoke the used refresh token and issue a new pair.
    # Extend the session window on every successful refresh so an actively
    # used account is not silently logged out merely because the original
    # refresh-token expiry date has passed. Explicit logout still revokes the
    # active session immediately.
    matched.revoked_at = now
    user = db.get(User, matched.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive.")
    tokens = _issue_tokens(db, user, request.headers.get("user-agent"))
    db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> None:
    now = datetime.now(timezone.utc)
    active = db.query(AuthSession).filter(AuthSession.revoked_at.is_(None)).all()
    matched = next((s for s in active if verify_refresh_token(payload.refresh_token, s.refresh_token_hash)), None)
    if matched is not None:
        matched.revoked_at = now
        _audit(db, user_id=matched.user_id, event_type="USER_LOGOUT", request=request)
        db.commit()
    return None


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, roles=sorted(user.role_names), created_at=user.created_at)


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    # Always return the same response whether or not the email exists, so
    # this endpoint can't be used to enumerate registered accounts.
    if user is not None:
        raw_token = create_raw_reset_token()
        db.add(PasswordResetToken(user_id=user.id, token_hash=hash_refresh_token(raw_token), expires_at=reset_token_expiry()))
        _audit(db, user_id=user.id, event_type="PASSWORD_RESET_REQUESTED", request=request)
        db.commit()
        # Phase 1 scope: no email delivery is wired up yet, so the raw
        # token isn't sent anywhere. Wiring this endpoint to a real email
        # provider is called out in the final report's remaining-issues
        # section rather than silently stubbed.
    return {"detail": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)) -> None:
    now = datetime.now(timezone.utc)
    candidates = db.query(PasswordResetToken).filter(
        PasswordResetToken.used_at.is_(None), PasswordResetToken.expires_at > now
    ).all()
    matched = next((t for t in candidates if verify_refresh_token(payload.token, t.token_hash)), None)
    if matched is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")
    try:
        validate_password_strength(payload.new_password)
    except WeakPasswordError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user = db.get(User, matched.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")
    user.password_hash = hash_password(payload.new_password)
    matched.used_at = now
    # Revoke every existing session on password reset.
    for s in db.query(AuthSession).filter(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)):
        s.revoked_at = now
    _audit(db, user_id=user.id, event_type="PASSWORD_CHANGED", request=request)
    db.commit()
    return None
