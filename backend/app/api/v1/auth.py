"""/api/v1/auth — accounts and cookie sessions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import AppContext, client_ip, get_ctx, get_user
from app.core.errors import APIError
from app.db.session import get_db
from app.models.entities import User
from app.schemas.api import ErrorResponse
from app.services import auth as svc

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class DeleteAccount(BaseModel):
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    id: str
    email: str
    is_admin: bool
    auth_enabled: bool


class AuthConfig(BaseModel):
    auth_enabled: bool
    signup_enabled: bool


def _out(user: User, ctx: AppContext) -> UserOut:
    return UserOut(id=user.id, email=user.email, is_admin=svc.is_admin(user, ctx.settings),
                   auth_enabled=ctx.settings.auth_enabled)


def _set_cookie(response: Response, ctx: AppContext, token: str) -> None:
    cfg = ctx.settings
    response.set_cookie(
        svc.COOKIE_NAME, token, max_age=cfg.session_days * 86400, httponly=True, path="/",
        secure=cfg.cookie_secure or cfg.cookie_samesite == "none", samesite=cfg.cookie_samesite,
    )


def _require_auth_mode(ctx: AppContext) -> None:
    if not ctx.settings.auth_enabled:
        raise APIError(404, "auth_disabled", "Accounts are disabled in local single-user mode.")


@router.get("/config", response_model=AuthConfig)
def auth_config(ctx: AppContext = Depends(get_ctx)) -> AuthConfig:
    return AuthConfig(auth_enabled=ctx.settings.auth_enabled, signup_enabled=ctx.settings.signup_enabled)


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}})
def signup(body: Credentials, request: Request, response: Response,
           ctx: AppContext = Depends(get_ctx), db: Session = Depends(get_db)) -> UserOut:
    _require_auth_mode(ctx)
    ctx.limiter.check(f"signup:{client_ip(request)}", ctx.settings.signups_per_hour_per_ip, 3600, "sign-ups")
    user = svc.signup(db, ctx.settings, body.email, body.password)
    _set_cookie(response, ctx, svc.create_session(db, ctx.settings, user))
    return _out(user, ctx)


@router.post("/login", response_model=UserOut, responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}})
def login(body: Credentials, request: Request, response: Response,
          ctx: AppContext = Depends(get_ctx), db: Session = Depends(get_db)) -> UserOut:
    _require_auth_mode(ctx)
    ctx.limiter.check(f"login:{client_ip(request)}", ctx.settings.logins_per_minute_per_ip, 60, "sign-in attempts")
    user = svc.authenticate(db, body.email, body.password)
    _set_cookie(response, ctx, svc.create_session(db, ctx.settings, user))
    return _out(user, ctx)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, ctx: AppContext = Depends(get_ctx), db: Session = Depends(get_db)) -> None:
    svc.end_session(db, request.cookies.get(svc.COOKIE_NAME))
    response.delete_cookie(svc.COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut, responses={401: {"model": ErrorResponse}})
def me(user: User = Depends(get_user), ctx: AppContext = Depends(get_ctx)) -> UserOut:
    return _out(user, ctx)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT, responses={401: {"model": ErrorResponse}})
def delete_me(body: DeleteAccount, response: Response, user: User = Depends(get_user),
              ctx: AppContext = Depends(get_ctx), db: Session = Depends(get_db)) -> None:
    _require_auth_mode(ctx)
    svc.authenticate(db, user.email, body.password)  # re-confirm before an irreversible action
    svc.delete_account(db, ctx.manager, ctx.worker, user)
    response.delete_cookie(svc.COOKIE_NAME, path="/")
