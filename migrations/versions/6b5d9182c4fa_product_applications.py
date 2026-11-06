"""Promote the three demo applications to product suites without changing identity."""

import time
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "6b5d9182c4fa"
down_revision = "9350e78ae917"
branch_labels = None
depends_on = None

# Freeze migration data independently of future changes to the bootstrap catalog.
PRODUCTS = (
    (
        "agent",
        "工具调用",
        "通过工具协作完成业务任务",
        "pp_code",
        "PP Code",
        "编程、代码审查、工程理解及通过工具完成开发任务",
    ),
    (
        "chat",
        "普通对话",
        "问答、翻译、摘要、文本生成",
        "pp_chat",
        "PP Chat",
        "对话、问答、写作、摘要及通用 AI 助手",
    ),
    (
        "vision",
        "图片理解",
        "理解截图、图表和文档中的图片",
        "pp_cad",
        "PP CAD",
        "CAD 绘图、图纸理解、设计辅助及相关业务任务",
    ),
)


def rename_applications(mappings):
    bind = op.get_bind()
    metadata = sa.MetaData()
    applications = sa.Table("applications", metadata, autoload_with=bind)
    grants = sa.Table("company_applications", metadata, autoload_with=bind)
    keys = sa.Table("access_keys", metadata, autoload_with=bind)
    companies = sa.Table("companies", metadata, autoload_with=bind)
    audit = sa.Table("audit_logs", metadata, autoload_with=bind)
    existing = {row["code"]: row for row in bind.execute(sa.select(applications)).mappings()}
    # Check the entire mapping before changing any row; never merge different identities.
    for source, target, name, description in mappings:
        if source in existing and target in existing:
            raise RuntimeError(f"Cannot rename application {source}: {target} already exists")
    for source, target, name, description in mappings:
        row = existing.get(source)
        if row is None:
            continue
        values = dict(code=target, name=name, description=description)
        bind.execute(applications.update().where(applications.c.id == row["id"]).values(**values))
        demo_grants = (
            sa.select(grants.c.id)
            .join(companies, companies.c.id == grants.c.company_id)
            .where(grants.c.application_id == row["id"], companies.c.code == "pp_admin")
        )
        bind.execute(
            keys.update()
            .where(
                keys.c.grant_id.in_(demo_grants),
                keys.c.name == f"pp_admin-{source}-local",
                keys.c.kind == "application",
            )
            .values(name=f"pp_admin-{target}-local")
        )
        bind.execute(
            audit.insert().values(
                id=uuid4().hex,
                actor=f"migration:{revision}",
                action="application.rename",
                target=row["id"],
                created_at=time.time(),
                details={"before": {key: row[key] for key in values}, "after": values},
            )
        )


def upgrade():
    rename_applications(
        [(old, code, name, description) for old, _, _, code, name, description in PRODUCTS]
    )


def downgrade():
    rename_applications(
        [(code, old, name, description) for old, name, description, code, _, _ in PRODUCTS]
    )
