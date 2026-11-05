import csv
import io
from datetime import datetime

from fastapi import Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import case, distinct, func, select

from pprouter.admin import admin
from pprouter.models import Application, Attempt, Company, GatewayRequest
from pprouter.records import BILLING_ZONE

METRICS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "image_tokens",
)


def filters(
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    company_id: str | None = None,
    application_id: str | None = None,
    environment: str | None = None,
    key_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    phase: str | None = Query(default=None, pattern="^(routing|completion)$"),
):
    return dict(
        month=month or datetime.now(BILLING_ZONE).strftime("%Y-%m"),
        company_id=company_id,
        application_id=application_id,
        environment=environment,
        key_id=key_id,
        provider=provider,
        model=model,
        phase=phase,
    )


def constraints(values):
    root, attempts = [], []
    for key, value in values.items():
        if value is not None:
            if key in ("provider", "model", "phase"):
                attempts.append(getattr(Attempt, key) == value)
            else:
                root.append(getattr(GatewayRequest, key) == value)
    return root, attempts


def aggregates():
    return [
        func.count(Attempt.id).label("upstream_calls"),
        func.count(distinct(Attempt.request_id)).label("business_requests"),
        func.sum(case((Attempt.status == "succeeded", 1), else_=0)).label("succeeded"),
        func.sum(case((Attempt.status == "failed", 1), else_=0)).label("failed"),
        func.sum(case((Attempt.usage_known.is_(False), 1), else_=0)).label("usage_unknown"),
        *[func.sum(getattr(Attempt, key)).label(key) for key in METRICS],
    ]


async def report(db, values):
    root, attempt = constraints(values)
    async with db.session() as session:
        calls = select(Attempt).join(GatewayRequest).where(*root, *attempt)
        summary = dict(
            (await session.execute(calls.with_only_columns(*aggregates()))).mappings().one()
        )
        requests = select(GatewayRequest).where(*root)
        if attempt:
            requests = requests.where(
                GatewayRequest.id.in_(calls.with_only_columns(Attempt.request_id))
            )
        metrics = await session.execute(
            requests.with_only_columns(
                func.count(GatewayRequest.id),
                func.sum(case((GatewayRequest.status == "succeeded", 1), else_=0)),
                func.sum(case((GatewayRequest.status == "failed", 1), else_=0)),
                func.sum(
                    case((GatewayRequest.status.in_(["interrupted", "cancelled"]), 1), else_=0)
                ),
            )
        )
        count, success, failure, interrupted = metrics.one()
        summary.update(
            business_requests=count,
            request_success=success or 0,
            request_failed=failure or 0,
            request_interrupted=interrupted or 0,
            success_rate=(success or 0) / count if count else None,
        )
        for key in ("succeeded", "failed", "usage_unknown"):
            summary[key] = summary[key] or 0
        grouped = (
            calls.join(Company, GatewayRequest.company_id == Company.id)
            .join(Application, GatewayRequest.application_id == Application.id)
            .with_only_columns(
                GatewayRequest.company_id,
                Company.code.label("company"),
                GatewayRequest.application_id,
                Application.code.label("application"),
                GatewayRequest.environment,
                Attempt.provider,
                Attempt.model,
                Attempt.phase,
                *aggregates(),
            )
            .group_by(
                GatewayRequest.company_id,
                Company.code,
                GatewayRequest.application_id,
                Application.code,
                GatewayRequest.environment,
                Attempt.provider,
                Attempt.model,
                Attempt.phase,
            )
            .order_by(Company.code, Application.code, Attempt.model, Attempt.phase)
        )
        rows = [dict(row) for row in (await session.execute(grouped)).mappings()]
        return {
            "month": values["month"],
            "timezone": "Asia/Shanghai",
            "summary": summary,
            "rows": rows,
            "note": "Confirmed usage only. Unknown usage is excluded from token sums. "
            "Business request counts across groups must not be added.",
        }


@admin.get("/reports/monthly")
async def monthly(request: Request, values=Depends(filters)):
    return await report(request.app.state.db, values)


@admin.get("/reports/monthly.csv")
async def monthly_csv(request: Request, values=Depends(filters)):
    data = await report(request.app.state.db, values)
    columns = [
        "month",
        "company",
        "application",
        "environment",
        "provider",
        "model",
        "phase",
        "business_requests",
        "upstream_calls",
        "succeeded",
        "failed",
        "usage_unknown",
        *METRICS,
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in data["rows"]:
        writer.writerow({"month": data["month"], **row})
    return Response(
        "\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="usage-{data["month"]}.csv"'},
    )
