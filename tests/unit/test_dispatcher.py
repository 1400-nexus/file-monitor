from pathlib import Path
from typing import Any, cast

import structlog.testing

from file_monitor.domain.ids import SenderId
from file_monitor.domain.models import FecParams
from file_monitor.ipc import codec
from file_monitor.ipc.errors import SendQueueFullError, UnknownSenderError
from file_monitor.services.constants import DISPATCH_RETRY_DELAY_SECONDS
from file_monitor.services.dispatcher import SessionDispatcher
from file_monitor.services.registry import SenderRegistry
from tests.fakes.fake_clock import FakeClock
from tests.fakes.fake_hasher import FakeHasher
from tests.fakes.fake_ipc_server import FakeIpcServer

ONE_BYTE_BLOCK_FEC = FecParams(k=1, n=1, symbol_bytes=1)
FILE_CONTENTS = b"0123456789"
TOTAL_BLOCKS = len(FILE_CONTENTS)


def make_registry(*sender_ids: SenderId) -> SenderRegistry:
    registry = SenderRegistry(FakeClock(), heartbeat_interval_seconds=5.0)
    for sender_id in sender_ids:
        registry.register(sender_id)
    return registry


def make_dispatcher(
    ipc: FakeIpcServer,
    registry: SenderRegistry,
    watch_root: Path,
    clock: FakeClock | None = None,
) -> SessionDispatcher:
    return SessionDispatcher(
        ipc=ipc,
        hasher=FakeHasher(),
        registry=registry,
        clock=clock if clock is not None else FakeClock(),
        fec_params=ONE_BYTE_BLOCK_FEC,
        watch_root=watch_root,
        target_host="10.0.0.1",
        base_port=9000,
    )


def blocks_from_sent(sent: list[tuple[SenderId, bytes]]) -> list[int]:
    # Each sender receives at most one AssignSession per session: shard
    # modulus/residue are planned once and only the send is retried, never
    # the plan, so there is never a second, conflicting message to resolve.
    blocks: list[int] = []
    for _sender_id, payload in sent:
        field_name, message = codec.decode(payload)
        assert field_name == "assign_session"
        message = cast(Any, message)
        manifest = message.manifest
        blocks.extend(
            block_id
            for block_id in range(manifest.total_blocks)
            if block_id % message.total_senders == manifest.sender_id
        )
    return blocks


async def test_three_active_senders_produce_disjoint_shards_covering_every_block(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "example.bin"
    file_path.write_bytes(FILE_CONTENTS)

    ipc = FakeIpcServer()
    registry = make_registry(SenderId(0), SenderId(1), SenderId(2))
    dispatcher = make_dispatcher(ipc, registry, tmp_path)

    session_id = await dispatcher.dispatch(file_path)

    assert session_id is not None
    assert len(ipc.sent) == 3
    assert {sender_id for sender_id, _ in ipc.sent} == {SenderId(0), SenderId(1), SenderId(2)}
    assert sorted(blocks_from_sent(ipc.sent)) == list(range(TOTAL_BLOCKS))
    assert dispatcher._dispatched_sessions[session_id] == [SenderId(0), SenderId(1), SenderId(2)]


async def test_empty_registry_returns_none_and_sends_nothing(tmp_path: Path) -> None:
    file_path = tmp_path / "example.bin"
    file_path.write_bytes(FILE_CONTENTS)

    ipc = FakeIpcServer()
    registry = make_registry()
    dispatcher = make_dispatcher(ipc, registry, tmp_path)

    session_id = await dispatcher.dispatch(file_path)

    assert session_id is None
    assert ipc.sent == []
    assert dispatcher._dispatched_sessions == {}


async def test_transient_failure_recovers_on_retry_without_touching_other_senders(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "example.bin"
    file_path.write_bytes(FILE_CONTENTS)

    ipc = FakeIpcServer()
    ipc.fail_next_send(SenderId(1), SendQueueFullError(SenderId(1)))
    registry = make_registry(SenderId(0), SenderId(1), SenderId(2))
    clock = FakeClock()
    dispatcher = make_dispatcher(ipc, registry, tmp_path, clock)

    session_id = await dispatcher.dispatch(file_path)

    assert session_id is not None
    # Each sender receives exactly one message: the retry re-sends the SAME
    # already-planned assignment to sender 1, it never re-plans shards or
    # sends a second message to 0/2.
    assert len(ipc.sent) == 3
    assert {sender_id for sender_id, _ in ipc.sent} == {SenderId(0), SenderId(1), SenderId(2)}
    assert sorted(blocks_from_sent(ipc.sent)) == list(range(TOTAL_BLOCKS))
    assert dispatcher._dispatched_sessions[session_id] == [SenderId(0), SenderId(1), SenderId(2)]
    # The retry genuinely waited for the queue to drain rather than spinning.
    assert clock.now() == DISPATCH_RETRY_DELAY_SECONDS


async def test_sender_that_exhausts_retries_is_lost_survivors_keep_original_shards(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "example.bin"
    file_path.write_bytes(FILE_CONTENTS)

    ipc = FakeIpcServer()
    # Both of sender 1's attempts fail: its shard (residue 1 of modulus 3,
    # planned from the original 3-sender set) is permanently lost, not
    # redistributed to 0 or 2 — 0 and 2 keep their original assignments.
    ipc.fail_next_send(SenderId(1), SendQueueFullError(SenderId(1)))
    ipc.fail_next_send(SenderId(1), SendQueueFullError(SenderId(1)))
    registry = make_registry(SenderId(0), SenderId(1), SenderId(2))
    dispatcher = make_dispatcher(ipc, registry, tmp_path)

    with structlog.testing.capture_logs() as captured_logs:
        session_id = await dispatcher.dispatch(file_path)

    assert session_id is not None
    sent_sender_ids = {sender_id for sender_id, _ in ipc.sent}
    assert sent_sender_ids == {SenderId(0), SenderId(2)}
    lost_blocks = [block_id for block_id in range(TOTAL_BLOCKS) if block_id % 3 == 1]
    assert sorted(blocks_from_sent(ipc.sent)) == [
        block_id for block_id in range(TOTAL_BLOCKS) if block_id not in lost_blocks
    ]
    assert dispatcher._dispatched_sessions[session_id] == [SenderId(0), SenderId(2)]

    partial_failure_logs = [
        entry for entry in captured_logs if entry["event"] == "dispatch_partially_failed"
    ]
    assert len(partial_failure_logs) == 1
    log_entry = partial_failure_logs[0]
    assert log_entry["session_id"] == session_id
    assert log_entry["failed_sender_ids"] == [SenderId(1)]
    # A compact (residue, modulus, count) summary, not the block enumeration:
    # residue 1 of modulus 3 identifies blocks {1, 4, 7} exactly.
    assert log_entry["lost_block_count"] == len(lost_blocks)
    assert log_entry["lost_shards"] == [
        {"sender_id": SenderId(1), "shard_residue": 1, "shard_modulus": 3, "block_count": 3}
    ]
    assert "lost_block_ids" not in log_entry


async def test_single_sender_that_exhausts_retries_returns_none(tmp_path: Path) -> None:
    file_path = tmp_path / "example.bin"
    file_path.write_bytes(FILE_CONTENTS)

    ipc = FakeIpcServer()
    ipc.fail_next_send(SenderId(0), SendQueueFullError(SenderId(0)))
    ipc.fail_next_send(SenderId(0), SendQueueFullError(SenderId(0)))
    registry = make_registry(SenderId(0))
    dispatcher = make_dispatcher(ipc, registry, tmp_path)

    session_id = await dispatcher.dispatch(file_path)

    assert session_id is None
    assert ipc.sent == []
    assert dispatcher._dispatched_sessions == {}


async def test_unknown_sender_error_is_not_retried_and_removes_sender_from_registry(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "example.bin"
    file_path.write_bytes(FILE_CONTENTS)

    ipc = FakeIpcServer()
    ipc.fail_next_send(SenderId(1), UnknownSenderError(SenderId(1)))
    registry = make_registry(SenderId(0), SenderId(1), SenderId(2))
    dispatcher = make_dispatcher(ipc, registry, tmp_path)

    await dispatcher.dispatch(file_path)

    # Only one attempt: UnknownSenderError means the peer is definitively
    # gone, so it is not worth retrying.
    assert {sender_id for sender_id, _ in ipc.sent} == {SenderId(0), SenderId(2)}
    assert registry.active_senders() == [SenderId(0), SenderId(2)]


async def test_send_queue_full_does_not_remove_sender_from_registry(tmp_path: Path) -> None:
    file_path = tmp_path / "example.bin"
    file_path.write_bytes(FILE_CONTENTS)

    ipc = FakeIpcServer()
    ipc.fail_next_send(SenderId(1), SendQueueFullError(SenderId(1)))
    ipc.fail_next_send(SenderId(1), SendQueueFullError(SenderId(1)))
    registry = make_registry(SenderId(0), SenderId(1), SenderId(2))
    dispatcher = make_dispatcher(ipc, registry, tmp_path)

    await dispatcher.dispatch(file_path)

    # The peer is alive, just backed up — still registered for next time.
    assert registry.active_senders() == [SenderId(0), SenderId(1), SenderId(2)]


async def test_complete_session_removes_the_dispatched_session_entry(tmp_path: Path) -> None:
    file_path = tmp_path / "example.bin"
    file_path.write_bytes(FILE_CONTENTS)

    ipc = FakeIpcServer()
    registry = make_registry(SenderId(0))
    dispatcher = make_dispatcher(ipc, registry, tmp_path)

    session_id = await dispatcher.dispatch(file_path)
    assert session_id is not None
    assert session_id in dispatcher._dispatched_sessions

    dispatcher.complete_session(session_id)

    assert session_id not in dispatcher._dispatched_sessions


def test_complete_session_on_an_unknown_session_id_does_not_raise() -> None:
    ipc = FakeIpcServer()
    registry = make_registry(SenderId(0))
    dispatcher = SessionDispatcher(
        ipc=ipc,
        hasher=FakeHasher(),
        registry=registry,
        clock=FakeClock(),
        fec_params=ONE_BYTE_BLOCK_FEC,
        watch_root=Path("/watch"),
        target_host="10.0.0.1",
        base_port=9000,
    )

    dispatcher.complete_session("never-dispatched")
