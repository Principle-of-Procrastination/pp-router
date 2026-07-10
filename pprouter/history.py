import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Protocol

import httpx

from pprouter.schemas import HistoryItem, HistorySummary, ModelStat


class HistoryStoreError(RuntimeError):
    pass


class HistoryStore(Protocol):
    def append(self, item: HistoryItem) -> None: ...

    def recent(self, limit: int) -> list[HistoryItem]: ...

    def summary(self) -> HistorySummary: ...

    def close(self) -> None: ...


class SQLiteHistoryStore:
    """Transactional local fallback for development without CloudBase credentials."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    query TEXT NOT NULL,
                    model TEXT NOT NULL,
                    tier TEXT,
                    forced INTEGER NOT NULL,
                    score REAL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_history_ts ON chat_history(ts DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_history_model ON chat_history(model)"
            )

    def append(self, item: HistoryItem) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO chat_history (
                    ts, query, model, tier, forced, score,
                    prompt_tokens, completion_tokens, total_tokens
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.ts,
                    item.query,
                    item.model,
                    item.tier,
                    int(item.forced),
                    item.score,
                    item.usage.prompt_tokens,
                    item.usage.completion_tokens,
                    item.usage.total_tokens,
                ),
            )

    def recent(self, limit: int) -> list[HistoryItem]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ts, query, model, tier, forced, score,
                       prompt_tokens, completion_tokens, total_tokens
                FROM chat_history
                ORDER BY ts DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_history_item_from_row(row) for row in rows]

    def summary(self) -> HistorySummary:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT model, COUNT(*) AS requests, COALESCE(SUM(total_tokens), 0)
                FROM chat_history
                GROUP BY model
                ORDER BY model
                """
            ).fetchall()
        by_model = {
            str(row[0]): ModelStat(requests=int(row[1]), total_tokens=int(row[2]))
            for row in rows
        }
        return HistorySummary(
            total_requests=sum(stat.requests for stat in by_model.values()),
            total_tokens=sum(stat.total_tokens for stat in by_model.values()),
            by_model=by_model,
        )

    def close(self) -> None:
        return None

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=5)


class CloudBaseHistoryStore:
    """CloudBase NoSQL REST store authenticated by a server-only API key."""

    def __init__(
        self,
        env_id: str,
        api_key: str,
        collection: str,
        *,
        timeout: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        base = (
            f"https://{env_id}.api.tcloudbasegateway.com/v1/database/"
            "instances/(default)/databases/(default)"
        )
        self._documents_url = f"{base}/collections/{collection}/documents"
        self._aggregate_url = f"{self._documents_url}/aggregations"
        self._client = client or httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        self._owns_client = client is None

    def append(self, item: HistoryItem) -> None:
        response = self._client.post(
            self._documents_url,
            json={"data": [item.model_dump(mode="json")]},
        )
        self._expect(response, {201})

    def recent(self, limit: int) -> list[HistoryItem]:
        response = self._client.get(
            self._documents_url,
            params={
                "query": "{}",
                "limit": limit,
                "order": json.dumps(
                    [{"field": "ts", "direction": "desc"}], separators=(",", ":")
                ),
            },
        )
        payload = self._expect(response, {200})
        raw_items = payload.get("list")
        if not isinstance(raw_items, list):
            raise HistoryStoreError("CloudBase history response is missing list")
        try:
            return [HistoryItem.model_validate(_decode_ejson(item)) for item in raw_items]
        except (TypeError, ValueError) as exc:
            raise HistoryStoreError("CloudBase history response is invalid") from exc

    def summary(self) -> HistorySummary:
        response = self._client.post(
            self._aggregate_url,
            json={
                "pipeline": [
                    {
                        "$group": {
                            "_id": "$model",
                            "requests": {"$sum": 1},
                            "total_tokens": {"$sum": "$usage.total_tokens"},
                        }
                    },
                    {"$sort": {"_id": 1}},
                ]
            },
        )
        payload = self._expect(response, {200})
        groups = payload.get("list")
        if not isinstance(groups, list):
            raise HistoryStoreError("CloudBase summary response is missing list")

        by_model: dict[str, ModelStat] = {}
        try:
            for raw_group in groups:
                group = _decode_ejson(raw_group)
                model = str(group["_id"])
                by_model[model] = ModelStat(
                    requests=int(group["requests"]),
                    total_tokens=int(group["total_tokens"]),
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoryStoreError("CloudBase summary response is invalid") from exc

        return HistorySummary(
            total_requests=sum(stat.requests for stat in by_model.values()),
            total_tokens=sum(stat.total_tokens for stat in by_model.values()),
            by_model=by_model,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @staticmethod
    def _expect(response: httpx.Response, expected: set[int]) -> dict[str, Any]:
        if response.status_code not in expected:
            request_id = response.headers.get("x-request-id", "unknown")
            raise HistoryStoreError(
                f"CloudBase history request failed with status {response.status_code} "
                f"(request_id={request_id})"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise HistoryStoreError("CloudBase history response is not JSON") from exc
        if not isinstance(payload, dict):
            raise HistoryStoreError("CloudBase history response is not an object")
        return payload


def _history_item_from_row(row: sqlite3.Row | tuple[Any, ...]) -> HistoryItem:
    return HistoryItem.model_validate(
        {
            "ts": row[0],
            "query": row[1],
            "model": row[2],
            "tier": row[3],
            "forced": bool(row[4]),
            "score": row[5],
            "usage": {
                "prompt_tokens": row[6],
                "completion_tokens": row[7],
                "total_tokens": row[8],
            },
        }
    )


def _decode_ejson(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_ejson(item) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"$numberInt"} or set(value) == {"$numberLong"}:
        return int(next(iter(value.values())))
    if set(value) == {"$numberDouble"} or set(value) == {"$numberDecimal"}:
        return float(next(iter(value.values())))
    if set(value) == {"$oid"}:
        return value["$oid"]
    return {key: _decode_ejson(item) for key, item in value.items()}
