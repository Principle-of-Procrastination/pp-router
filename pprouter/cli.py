import argparse
import asyncio
import json
import os
from pathlib import Path

from pprouter.bootstrap import initialize
from pprouter.config import Settings
from pprouter.db import Database, migrate


async def init(settings, output):
    migrate(settings.database_path)
    db = Database(settings)
    try:
        credentials = await initialize(db, os.getenv("PP_ADMIN_PASSWORD") or None)
    finally:
        await db.close()
    if not credentials:
        print("Already initialized. Password and keys were not changed.")
        return
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Refuse to overwrite credentials from an earlier initialization.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(credentials, stream, ensure_ascii=False, indent=2)
        print(f"One-time credentials saved to {path.resolve()} (mode 0600).")
    else:
        print(json.dumps(credentials, ensure_ascii=False, indent=2))
        print("Save these credentials now. They cannot be retrieved again.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "migrate"])
    parser.add_argument("--credentials-file")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "migrate":
        migrate(settings.database_path)
    else:
        asyncio.run(init(settings, args.credentials_file))


if __name__ == "__main__":
    main()
