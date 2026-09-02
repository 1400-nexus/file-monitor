from pathlib import Path
from typing import Any, cast

from file_monitor.domain.ids import SenderId
from file_monitor.domain.models import FecParams
from file_monitor.ipc import codec
from file_monitor.ipc.errors import SendQueueFullError
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
    ipc: FakeIpcServer, registry: SenderRegistry, watch_root: Path
) -> SessionDispatcher:
    return SessionDispatcher(
        ipc=ipc,
        hasher=FakeHasher(),
        registry=registry,
        fec_params=ONE_BYTE_BLOCK_FEC,
        watch_root=watch_root,
        target_host="10.0.0.1",
        base_port=9000,
    )


def blocks_from_sent(sent: list[tuple[SenderId, bytes]]) -> list[int]:
    # A retry resends a fresh (superseding) assignment to every survivor, not
    # just the sender that failed, since the modulus changes for everyone
    # once the sender count shrinks. Only each sender's latest message is
    # authoritative.
    latest_payload_by_sender: dict[SenderId, bytes] = dict(sent)

    blocks: list[int] = []
    for payload in latest_payload_by_sender.values():
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


async def test_failed_sender_is_dropped_and_survivors_get_replanned_assignment(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "example.bin"
    file_path.write_bytes(FILE_CONTENTS)

    ipc = FakeIpcServer()
    ipc.fail_next_send(SenderId(1), SendQueueFullError(SenderId(1)))
    registry = make_registry(SenderId(0), SenderId(1), SenderId(2))
    dispatcher = make_dispatcher(ipc, registry, tmp_path)

    session_id = await dispatcher.dispatch(file_path)

    assert session_id is not None
    sent_sender_ids = {sender_id for sender_id, _ in ipc.sent}
    assert sent_sender_ids == {SenderId(0), SenderId(2)}
    assert sorted(blocks_from_sent(ipc.sent)) == list(range(TOTAL_BLOCKS))
    assert dispatcher._dispatched_sessions[session_id] == [SenderId(0), SenderId(2)]


async def test_dispatch_gives_up_after_one_retry_if_the_retry_also_fails(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "example.bin"
    file_path.write_bytes(FILE_CONTENTS)

    ipc = FakeIpcServer()
    # Attempt 1: sender 1 fails and is dropped; sender 2 succeeds. Attempt 2
    # (the retry, over survivors [0, 2]): sender 2 fails this time too, so the
    # retry itself has a failure and dispatch must give up rather than retry
    # again.
    ipc.fail_next_send(SenderId(1), SendQueueFullError(SenderId(1)))
    ipc.succeed_next_send(SenderId(2))
    ipc.fail_next_send(SenderId(2), SendQueueFullError(SenderId(2)))
    registry = make_registry(SenderId(0), SenderId(1), SenderId(2))
    dispatcher = make_dispatcher(ipc, registry, tmp_path)

    session_id = await dispatcher.dispatch(file_path)

    assert session_id is None
    assert dispatcher._dispatched_sessions == {}
