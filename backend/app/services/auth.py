"""Accounts and login sessions.

Sessions are opaque random tokens in an HttpOnly cookie; the database stores
only their SHA-256, so a leaked database cannot be replayed as logins.
"""

from __future__ import annotations

import contextlib
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import AppSettings
from app.core.errors import APIError
from app.core.security import hash_password, new_session_token, token_hash, verify_password
from app.models.entities import LOCAL_USER_ID, AuthSession, Document, User
from app.rag.engine import EngineManager
from app.workers.ingestion import IngestionWorker
from querydoc.exceptions import DocumentNotFoundError

log = logging.getLogger("querydoc.api.auth")
COOKIE_NAME = "querydoc_session"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
# Verified against when the email is unknown, so response time does not reveal which emails exist.
_DUMMY_HASH = hash_password("not-a-real-password")


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise APIError(422, "invalid_email", "Enter a valid email address.")
    return email


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise APIError(422, "weak_password", "Use at least 8 characters.")
    if len(password) > 128:
        raise APIError(422, "weak_password", "Use at most 128 characters.")


def is_admin(user: User, cfg: AppSettings) -> bool:
    if not cfg.auth_enabled:
        return True
    return user.is_admin or user.email in {e.lower() for e in cfg.admin_emails}


def signup(db: Session, cfg: AppSettings, email: str, password: str) -> User:
    if not cfg.signup_enabled:
        raise APIError(403, "signup_disabled", "New sign-ups are currently closed.")
    email = normalize_email(email)
    validate_password(password)
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise APIError(409, "email_taken", "An account with this email already exists. Sign in instead.")
    user = User(email=email, password_hash=hash_password(password),
                is_admin=email in {e.lower() for e in cfg.admin_emails})
    db.add(user)
    db.flush()
    log.info("user signed up", extra={"fields": {"user_id": user.id}})
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == (email or "").strip().lower()))
    if user is None or not user.password_hash:
        verify_password(password, _DUMMY_HASH)
        raise APIError(401, "invalid_credentials", "Incorrect email or password.")
    if not verify_password(password, user.password_hash):
        raise APIError(401, "invalid_credentials", "Incorrect email or password.")
    return user


def create_session(db: Session, cfg: AppSettings, user: User) -> str:
    now = datetime.now(timezone.utc)
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    token = new_session_token()
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id, expires_at=now + timedelta(days=cfg.session_days)))
    user.last_login_at = now
    return token


def user_for_token(db: Session, token: str | None) -> User | None:
    if not token or len(token) > 200:
        return None
    sess = db.get(AuthSession, token_hash(token))
    if sess is None or _utc(sess.expires_at) < datetime.now(timezone.utc):
        return None
    return db.get(User, sess.user_id)


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))


def local_user(db: Session) -> User:
    user = db.get(User, LOCAL_USER_ID)
    if user is None:  # created by the migration; recreate if someone deleted it
        user = User(id=LOCAL_USER_ID, email="local@localhost", password_hash="", is_admin=True)
        db.add(user)
        db.flush()
    return user


def delete_account(db: Session, manager: EngineManager, worker: IngestionWorker, user: User) -> int:
    """Remove the user's vectors, stored PDFs and rows. Returns the number of documents removed."""
    docs = list(db.scalars(select(Document).where(Document.owner_id == user.id)))
    if any(d.status in {"queued", "processing"} for d in docs):
        raise APIError(409, "documents_busy", "Some documents are still processing; try again when they finish.")
    for d in docs:
        with contextlib.suppress(DocumentNotFoundError):
            manager.service.delete_document(d.id)
        worker.upload_path(d.id).unlink(missing_ok=True)
    db.delete(user)  # cascades to documents, conversations, messages, sessions, query logs
    log.info("account deleted", extra={"fields": {"user_id": user.id, "documents": len(docs)}})
    return len(docs)
