import time
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pprouter.limits import CONTEXT_TOKENS, OUTPUT_TOKENS


def uid() -> str:
    return uuid4().hex


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    external_id: Mapped[str | None] = mapped_column(String, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class CompanyApplication(Base):
    __tablename__ = "company_applications"
    __table_args__ = (UniqueConstraint("company_id", "application_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_models: Mapped[list] = mapped_column(JSON)
    rpm: Mapped[int] = mapped_column(Integer, default=60)
    concurrency: Mapped[int] = mapped_column(Integer, default=4)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=OUTPUT_TOKENS)
    policy: Mapped[dict] = mapped_column(JSON)
    policy_version: Mapped[int] = mapped_column(Integer, default=1)


class AccessKey(Base):
    __tablename__ = "access_keys"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'application' AND grant_id IS NOT NULL) OR "
            "(kind = 'provisioning' AND grant_id IS NULL)"
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String)
    grant_id: Mapped[str | None] = mapped_column(ForeignKey("company_applications.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    environment: Mapped[str] = mapped_column(String, default="local")
    prefix: Mapped[str] = mapped_column(String)
    digest: Mapped[str] = mapped_column(String, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id"))
    digest: Mapped[str] = mapped_column(String, unique=True)
    csrf_token: Mapped[str] = mapped_column(String)
    expires_at: Mapped[float] = mapped_column(Float)


class Model(Base):
    __tablename__ = "models"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    vision: Mapped[bool] = mapped_column(Boolean)
    tools: Mapped[bool] = mapped_column(Boolean, default=True)
    formats: Mapped[list] = mapped_column(JSON)
    context_tokens: Mapped[int] = mapped_column(Integer, default=CONTEXT_TOKENS)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=OUTPUT_TOKENS)


class GatewayRequest(Base):
    __tablename__ = "requests"
    __table_args__ = (Index("ix_requests_month_company", "month", "company_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    grant_id: Mapped[str] = mapped_column(ForeignKey("company_applications.id"))
    key_id: Mapped[str] = mapped_column(ForeignKey("access_keys.id"))
    environment: Mapped[str] = mapped_column(String)
    month: Mapped[str] = mapped_column(String)
    requested_model: Mapped[str] = mapped_column(String)
    actual_model: Mapped[str | None] = mapped_column(String)
    trace_id: Mapped[str | None] = mapped_column(String)
    user_hash: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="running")
    error_code: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[float] = mapped_column(Float, default=time.time)
    finished_at: Mapped[float | None] = mapped_column(Float)
    routing: Mapped[dict] = mapped_column(JSON, default=dict)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("request_id", "ordinal"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    reported_model: Mapped[str | None] = mapped_column(String)
    upstream_request_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="running")
    error_code: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[float] = mapped_column(Float, default=time.time)
    finished_at: Mapped[float | None] = mapped_column(Float)
    first_token_ms: Mapped[float | None] = mapped_column(Float)
    usage_known: Mapped[bool] = mapped_column(Boolean, default=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    image_tokens: Mapped[int | None] = mapped_column(Integer)
    raw_usage: Mapped[dict | None] = mapped_column(JSON)


class ToolBinding(Base):
    __tablename__ = "tool_bindings"
    __table_args__ = (UniqueConstraint("grant_id", "environment", "tool_call_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    grant_id: Mapped[str] = mapped_column(ForeignKey("company_applications.id"))
    environment: Mapped[str] = mapped_column(String)
    tool_call_id: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    mode: Mapped[dict] = mapped_column(JSON)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    target: Mapped[str] = mapped_column(String)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
