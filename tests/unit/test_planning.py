import pytest

from file_monitor.domain.ids import BlockId, SenderId
from file_monitor.domain.models import FecParams
from file_monitor.domain.planning import compute_block_plans, derive_shard_assignments

FEC = FecParams(k=4, n=6, symbol_bytes=10)


def test_file_exactly_one_block_long() -> None:
    plans = compute_block_plans(FEC.block_size, FEC)
    assert len(plans) == 1
    assert plans[0].block_id == BlockId(0)
    assert plans[0].start_byte == 0
    assert plans[0].end_byte == FEC.block_size


def test_file_one_byte_over_one_block_produces_two_blocks_second_short() -> None:
    plans = compute_block_plans(FEC.block_size + 1, FEC)
    assert len(plans) == 2
    assert plans[0].start_byte == 0
    assert plans[0].end_byte == FEC.block_size
    assert plans[1].start_byte == FEC.block_size
    assert plans[1].end_byte == FEC.block_size + 1


def test_file_smaller_than_one_symbol() -> None:
    file_size = FEC.symbol_bytes - 1
    plans = compute_block_plans(file_size, FEC)
    assert len(plans) == 1
    assert plans[0].start_byte == 0
    assert plans[0].end_byte == file_size


def test_zero_byte_file_produces_no_blocks() -> None:
    plans = compute_block_plans(0, FEC)
    assert plans == []


@pytest.mark.parametrize("file_size", [1, 39, 40, 41, 79, 80, 81, 401])
def test_block_plans_are_contiguous_non_overlapping_and_cover_file_size(file_size: int) -> None:
    plans = compute_block_plans(file_size, FEC)
    covered = 0
    for i, plan in enumerate(plans):
        assert plan.start_byte == covered, f"gap or overlap before block {i}"
        assert plan.end_byte > plan.start_byte
        covered = plan.end_byte
    assert covered == file_size


@pytest.mark.parametrize("sender_count", [1, 2, 3])
def test_derive_shard_assignments_sender_counts(sender_count: int) -> None:
    total_blocks = 10
    senders = [SenderId(i) for i in range(sender_count)]
    assignments = derive_shard_assignments(total_blocks, senders, base_port=9000)

    assert len(assignments) == sender_count
    all_blocks = sorted(b for a in assignments for b in a.assigned_blocks)
    assert all_blocks == list(range(total_blocks))


@pytest.mark.parametrize("sender_count", [1, 2, 3])
def test_target_ports_are_base_port_plus_index(sender_count: int) -> None:
    senders = [SenderId(i) for i in range(sender_count)]
    assignments = derive_shard_assignments(10, senders, base_port=9000)
    for index, assignment in enumerate(assignments):
        assert assignment.target_port == 9000 + index
