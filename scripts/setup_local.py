from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
path = ROOT / ".env"
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    pass
else:
    with os.fdopen(fd, "w") as stream:
        stream.write((ROOT / ".env.example").read_text())
    print("Created .env. Add provider credentials when ready for live calls.")
