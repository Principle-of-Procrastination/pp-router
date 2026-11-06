"""Unify service context/output limits without replacing identities or usage."""

import time
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "c7218f4b0ad6"
down_revision = "6b5d9182c4fa"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()
    audit = sa.Table("audit_logs", metadata, autoload_with=bind)
    for name, limits in (
        ("models", {"context_tokens": 256000, "max_output_tokens": 32000}),
        ("company_applications", {"max_output_tokens": 32000}),
    ):
        table = sa.Table(name, metadata, autoload_with=bind)
        for row in list(bind.execute(sa.select(table)).mappings()):
            if all(row[key] == value for key, value in limits.items()):
                continue
            after = dict(limits)
            if name == "company_applications":
                after["policy_version"] = row["policy_version"] + 1
            before = {key: row[key] for key in after}
            bind.execute(table.update().where(table.c.id == row["id"]).values(**after))
            bind.execute(
                audit.insert().values(
                    id=uuid4().hex,
                    actor=f"migration:{revision}",
                    action="limits.update",
                    target=row["id"],
                    created_at=time.time(),
                    details={"table": name, "before": before, "after": after},
                )
            )


def downgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()
    audit = sa.Table("audit_logs", metadata, autoload_with=bind)
    tables = {
        name: sa.Table(name, metadata, autoload_with=bind)
        for name in ("models", "company_applications")
    }
    changes = list(
        bind.execute(
            sa.select(audit).where(
                audit.c.actor == f"migration:{revision}", audit.c.action == "limits.update"
            )
        ).mappings()
    )
    # Refuse to overwrite a policy edited since the migration; check all rows first.
    for change in changes:
        details = change["details"]
        table = tables[details["table"]]
        row = bind.execute(sa.select(table).where(table.c.id == change["target"])).mappings().first()
        if row is None or any(row[key] != value for key, value in details["after"].items()):
            raise RuntimeError("Token limits changed after migration; restore a reviewed backup")
    for change in changes:
        details = change["details"]
        table = tables[details["table"]]
        bind.execute(
            table.update().where(table.c.id == change["target"]).values(**details["before"])
        )
        bind.execute(audit.delete().where(audit.c.id == change["id"]))
