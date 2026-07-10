import httpx

from pprouter.history import CloudBaseHistoryStore, SQLiteHistoryStore
from pprouter.schemas import HistoryItem, Usage


def _item() -> HistoryItem:
    return HistoryItem(
        ts="2026-07-10T16:30:00+08:00",
        query="解释消息队列",
        model="glm-4.7",
        tier="MEDIUM",
        usage=Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )


def test_sqlite_history_is_bounded_and_aggregated(tmp_path) -> None:
    store = SQLiteHistoryStore(tmp_path / "history.db")
    store.append(_item())
    store.append(_item())

    assert len(store.recent(1)) == 1
    summary = store.summary()
    assert summary.total_requests == 2
    assert summary.total_tokens == 60
    assert summary.by_model["glm-4.7"].requests == 2


def test_cloudbase_history_decodes_ejson() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/aggregations"):
            return httpx.Response(
                200,
                json={
                    "list": [
                        {
                            "_id": "glm-4.7",
                            "requests": {"$numberInt": "2"},
                            "total_tokens": {"$numberLong": "60"},
                        }
                    ]
                },
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "list": [
                        {
                            "_id": {"$oid": "507f1f77bcf86cd799439011"},
                            "ts": "2026-07-10T16:30:00+08:00",
                            "query": "解释消息队列",
                            "model": "glm-4.7",
                            "tier": "MEDIUM",
                            "forced": False,
                            "score": {"$numberDouble": "0.25"},
                            "usage": {
                                "prompt_tokens": {"$numberInt": "10"},
                                "completion_tokens": {"$numberInt": "20"},
                                "total_tokens": {"$numberInt": "30"},
                            },
                        }
                    ]
                },
            )
        return httpx.Response(201, json={"insertedIds": ["id"]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = CloudBaseHistoryStore("env", "key", "history", client=client)
    store.append(_item())

    assert store.recent(1)[0].usage.total_tokens == 30
    assert store.summary().total_tokens == 60
