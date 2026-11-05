import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pprouter.config import ROOT, Settings
from pprouter.models import Attempt, GatewayRequest


def migrate(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path.resolve()}")
    command.upgrade(cfg, "head")
    path.chmod(0o600)


class Database:
    def __init__(self, settings: Settings):
        self.engine = create_async_engine(settings.database_url, connect_args={"timeout": 5})

        @event.listens_for(self.engine.sync_engine, "connect")
        def sqlite_pragmas(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        self.session = async_sessionmaker(self.engine, expire_on_commit=False)

    async def recover(self):
        async with self.session.begin() as session:
            for entity in (GatewayRequest, Attempt):
                await session.execute(
                    update(entity)
                    .where(entity.status == "running")
                    .values(
                        status="interrupted",
                        error_code="process_interrupted",
                        finished_at=time.time(),
                    )
                )

    async def close(self):
        await self.engine.dispose()
