import asyncio
from typing import cast

from fastapi import Request

from pprouter.api import _HEARTBEAT, _iterate_stream


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


async def _slow_stream():
    await asyncio.sleep(0.04)
    yield "chunk"


def test_heartbeat_does_not_cancel_pending_stream_read() -> None:
    async def collect() -> list[object]:
        return [
            item
            async for item in _iterate_stream(
                _slow_stream(),
                cast(Request, ConnectedRequest()),
                heartbeat_seconds=0.01,
                timeout_seconds=0.2,
            )
        ]

    items = asyncio.run(collect())
    assert _HEARTBEAT in items
    assert items[-1] == "chunk"
