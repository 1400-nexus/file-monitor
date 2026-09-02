from file_monitor.domain.ids import SenderId
from file_monitor.services.constants import MISSED_HEARTBEAT_LIMIT
from file_monitor.services.registry import SenderRegistry
from tests.fakes.fake_clock import FakeClock

HEARTBEAT_INTERVAL_SECONDS = 5.0


def make_registry(clock: FakeClock) -> SenderRegistry:
    return SenderRegistry(clock, heartbeat_interval_seconds=HEARTBEAT_INTERVAL_SECONDS)


def test_register_adds_sender_as_active() -> None:
    registry = make_registry(FakeClock())
    registry.register(SenderId(1))
    assert registry.active_senders() == [SenderId(1)]


def test_active_senders_is_sorted_and_stable() -> None:
    registry = make_registry(FakeClock())
    registry.register(SenderId(3))
    registry.register(SenderId(1))
    registry.register(SenderId(2))
    assert registry.active_senders() == [SenderId(1), SenderId(2), SenderId(3)]
    assert registry.active_senders() == registry.active_senders()


def test_refresh_keeps_sender_alive_across_heartbeats() -> None:
    clock = FakeClock()
    registry = make_registry(clock)
    registry.register(SenderId(1))

    for _ in range(5):
        clock.advance(HEARTBEAT_INTERVAL_SECONDS - 0.001)
        registry.refresh(SenderId(1))

    assert registry.active_senders() == [SenderId(1)]


def test_sender_drops_out_after_exactly_the_configured_timeout() -> None:
    clock = FakeClock()
    registry = make_registry(clock)
    registry.register(SenderId(1))

    timeout_seconds = HEARTBEAT_INTERVAL_SECONDS * MISSED_HEARTBEAT_LIMIT
    clock.advance(timeout_seconds - 0.001)
    assert registry.active_senders() == [SenderId(1)]

    clock.advance(0.002)
    assert registry.active_senders() == []


def test_disconnect_removes_sender_immediately() -> None:
    registry = make_registry(FakeClock())
    registry.register(SenderId(1))
    registry.remove(SenderId(1))
    assert registry.active_senders() == []


def test_removing_an_unknown_sender_is_a_noop() -> None:
    registry = make_registry(FakeClock())
    registry.remove(SenderId(999))
    assert registry.active_senders() == []


def test_dead_sender_no_longer_affects_active_senders_after_purge() -> None:
    clock = FakeClock()
    registry = make_registry(clock)
    registry.register(SenderId(1))
    registry.register(SenderId(2))

    clock.advance(HEARTBEAT_INTERVAL_SECONDS * MISSED_HEARTBEAT_LIMIT)
    registry.refresh(SenderId(2))

    assert registry.active_senders() == [SenderId(2)]
