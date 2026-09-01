from hypothesis import given
from hypothesis import strategies as st

from file_monitor.domain.ids import SenderId
from file_monitor.domain.models import FecParams
from file_monitor.domain.planning import calculate_block_count, derive_shard_assignments

FEC = FecParams(k=4, n=6, symbol_bytes=10)


@given(
    file_size=st.integers(min_value=0, max_value=10_000_000),
    sender_count=st.integers(min_value=1, max_value=3),
)
def test_every_block_assigned_exactly_once(file_size: int, sender_count: int) -> None:
    total_blocks = calculate_block_count(file_size, FEC)
    senders = [SenderId(i) for i in range(sender_count)]

    assignments = derive_shard_assignments(total_blocks, senders, base_port=9000)

    all_assigned = sorted(block for a in assignments for block in a.assigned_blocks)
    assert all_assigned == list(range(total_blocks))
