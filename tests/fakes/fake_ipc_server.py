import asyncio
from collections.abc import AsyncIterator

from file_monitor.domain.ids import SenderId


class FakeIpcServer:
    def __init__(self) -> None:
        self.sent: list[tuple[SenderId, bytes]] = []
        self._pending_outcomes: dict[SenderId, list[Exception | None]] = {}
        self._incoming: asyncio.Queue[tuple[SenderId, bytes]] = asyncio.Queue()

    def fail_next_send(self, sender_id: SenderId, error: Exception) -> None:
        self._pending_outcomes.setdefault(sender_id, []).append(error)

    def succeed_next_send(self, sender_id: SenderId) -> None:
        self._pending_outcomes.setdefault(sender_id, []).append(None)

    async def serve(self) -> None:
        return None

    async def send(self, sender_id: SenderId, payload: bytes) -> None:
        pending = self._pending_outcomes.get(sender_id)
        if pending:
            outcome = pending.pop(0)
            if outcome is not None:
                raise outcome
        self.sent.append((sender_id, payload))

    def incoming(self) -> AsyncIterator[tuple[SenderId, bytes]]:
        return self._iter_incoming()

    async def _iter_incoming(self) -> AsyncIterator[tuple[SenderId, bytes]]:
        while True:
            yield await self._incoming.get()
