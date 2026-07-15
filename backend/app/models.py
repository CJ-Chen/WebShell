from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def uuid4() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(16), default="user", index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    sessions: Mapped[List["WebSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    targets: Mapped[List["TargetHost"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class WebSession(Base):
    __tablename__ = "web_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class EncryptedCredential(Base):
    __tablename__ = "encrypted_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TargetHost(Base):
    __tablename__ = "target_hosts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("encrypted_credentials.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(80))
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str] = mapped_column(String(128))
    auth_method: Mapped[str] = mapped_column(String(16))
    default_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    host_key_algorithm: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    host_key_fingerprint: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="unverified")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship(back_populates="targets")
    credential: Mapped[Optional[EncryptedCredential]] = relationship(cascade="all, delete")
    terminals: Mapped[List["TerminalSession"]] = relationship(
        back_populates="target", cascade="all, delete-orphan"
    )


class TerminalSession(Base):
    __tablename__ = "terminal_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("target_hosts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    remote_session_name: Mapped[str] = mapped_column(String(80), unique=True)
    persistence_mode: Mapped[str] = mapped_column(String(16), default="shell")
    status: Mapped[str] = mapped_column(String(16), default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    last_connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    target: Mapped[TargetHost] = relationship(back_populates="terminals")


class DestinationRule(Base):
    __tablename__ = "destination_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(String(255))
    port_min: Mapped[int] = mapped_column(Integer, default=22)
    port_max: Mapped[int] = mapped_column(Integer, default=22)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), default="success")
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
