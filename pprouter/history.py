import threading
from pathlib import Path

from pprouter.schemas import HistoryItem


class HistoryStore:
    """Append-only JSONL store of past /chat requests (query, model, usage)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def append(self, item: HistoryItem) -> None:
        line = item.model_dump_json()
        with self._lock, self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read_all(self) -> list[HistoryItem]:
        if not self._path.exists():
            return []
        with self._lock:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        return [HistoryItem.model_validate_json(line) for line in lines if line.strip()]
