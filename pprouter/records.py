import time
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from pprouter.errors import GatewayError
from pprouter.models import Attempt, GatewayRequest, ToolBinding
from pprouter.providers import normalize_usage
from pprouter.security import digest

BILLING_ZONE = ZoneInfo("Asia/Shanghai")


class Records:
    def __init__(self, db):
        self.db = db

    async def start_request(self, caller, req, request_id, trace_id=None):
        now = time.time()
        async with self.db.session.begin() as session:
            session.add(
                GatewayRequest(
                    id=request_id,
                    company_id=caller.company.id,
                    application_id=caller.application.id,
                    grant_id=caller.grant.id,
                    key_id=caller.key.id,
                    environment=caller.key.environment,
                    month=datetime.fromtimestamp(now, BILLING_ZONE).strftime("%Y-%m"),
                    requested_model=req.model,
                    trace_id=trace_id,
                    started_at=now,
                    user_hash=digest(caller.company.id + ":" + req.user) if req.user else None,
                )
            )

    async def routing(self, request_id, info):
        async with self.db.session.begin() as session:
            row = await session.get(GatewayRequest, request_id)
            row.routing = info

    async def start_attempt(self, request_id, ordinal, phase, model):
        async with self.db.session.begin() as session:
            attempt = Attempt(
                request_id=request_id,
                ordinal=ordinal,
                phase=phase,
                provider=model.provider,
                model=model.id,
            )
            session.add(attempt)
            await session.flush()
            return attempt.id

    async def finish_attempt(
        self,
        attempt_id,
        *,
        status,
        usage=None,
        upstream_id=None,
        reported_model=None,
        error_code=None,
        first_token_ms=None,
        caller=None,
        tool_ids=(),
        mode=None,
    ):
        async with self.db.session.begin() as session:
            row = await session.get(Attempt, attempt_id)
            if row.status != "running":
                return
            row.status = status
            row.error_code = error_code
            row.finished_at = time.time()
            row.upstream_request_id = upstream_id[:256] if isinstance(upstream_id, str) else None
            row.reported_model = reported_model[:256] if isinstance(reported_model, str) else None
            row.first_token_ms = first_token_ms
            for key, value in normalize_usage(usage).items():
                setattr(row, key, value)
            if caller and status == "succeeded":
                for tool_id in set(tool_ids):
                    existing = await session.scalar(
                        select(ToolBinding).where(
                            ToolBinding.grant_id == caller.grant.id,
                            ToolBinding.environment == caller.key.environment,
                            ToolBinding.tool_call_id == tool_id,
                        )
                    )
                    if existing:
                        # Never replace a live binding with a different model/mode.
                        if existing.model != row.model or existing.mode != mode:
                            raise GatewayError(
                                502,
                                "tool_binding_collision",
                                "Upstream reused a tool ID across incompatible models.",
                            )
                    else:
                        session.add(
                            ToolBinding(
                                grant_id=caller.grant.id,
                                environment=caller.key.environment,
                                tool_call_id=tool_id,
                                model=row.model,
                                mode=mode or {},
                                request_id=row.request_id,
                            )
                        )

    async def finish_request(self, request_id, status, model=None, error=None):
        async with self.db.session.begin() as session:
            row = await session.get(GatewayRequest, request_id)
            if row.status == "running":
                row.status = status
                row.actual_model = model
                row.error_code = error
                row.finished_at = time.time()

    async def tool_binding(self, caller, ids):
        async with self.db.session() as session:
            bindings = list(
                await session.scalars(
                    select(ToolBinding).where(
                        ToolBinding.grant_id == caller.grant.id,
                        ToolBinding.environment == caller.key.environment,
                        ToolBinding.tool_call_id.in_(ids),
                    )
                )
            )
            if len(bindings) != len(set(ids)):
                return None
            if len({(b.model, str(sorted(b.mode.items()))) for b in bindings}) != 1:
                return None
            return bindings[0]
