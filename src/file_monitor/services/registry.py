from file_monitor.domain.ids import SenderId
from file_monitor.ports.protocols import Clock
from file_monitor.services.constants import MISSED_HEARTBEAT_LIMIT


class SenderRegistry:
    def __init__(self, clock: Clock, heartbeat_interval_seconds: float) -> None:
        self._clock: Clock = clock
        self._timeout_seconds: float = heartbeat_interval_seconds * MISSED_HEARTBEAT_LIMIT
        self._last_seen: dict[SenderId, float] = {}

    def register(self, sender_id: SenderId) -> None:
        self._last_seen[sender_id] = self._clock.now()

    def refresh(self, sender_id: SenderId) -> None:
        self.register(sender_id)

    def remove(self, sender_id: SenderId) -> None:
        self._last_seen.pop(sender_id, None)

    def active_senders(self) -> list[SenderId]:
        self._purge_expired()
        return sorted(self._last_seen)

    def _purge_expired(self) -> None:
        now = self._clock.now()
        expired = [
            sender_id
            for sender_id, last_seen in self._last_seen.items()
            if now - last_seen >= self._timeout_seconds
        ]
        for sender_id in expired:
            del self._last_seen[sender_id]
