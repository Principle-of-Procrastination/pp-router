"""Dedicated throwaway test server. Never imported by the production entrypoint."""

import asyncio
from pathlib import Path
import sys
import tempfile

import uvicorn

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from conftest import FakeProviders  # noqa: E402
from pprouter.bootstrap import initialize  # noqa: E402
from pprouter.config import Settings  # noqa: E402
from pprouter.db import Database, migrate  # noqa: E402
from pprouter.main import create_app  # noqa: E402


async def seed(settings):
    db = Database(settings)
    try:
        await initialize(db, "e2e-only-test-password")
    finally:
        await db.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="pp-router-e2e-") as directory:
        settings = Settings(
            database_path=Path(directory) / "test.db", allowed_origins=("http://127.0.0.1:5174",)
        )
        migrate(settings.database_path)
        asyncio.run(seed(settings))
        uvicorn.run(
            create_app(settings, FakeProviders()), host="127.0.0.1", port=4001, access_log=False
        )
