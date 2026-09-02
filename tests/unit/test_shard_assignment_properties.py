from hypothesis import given
from hypothesis import strategies as st

from file_monitor.domain.ids import SenderId
from file_monitor.domain.models import FecParams
from file_monitor.domain.planning import calculate_block_count, derive_shard_assignments

FEC = FecParams(k=4, n=6, symbol_bytes=10)

sender_ids_strategy = st.lists(
    st.integers(min_value=0, max_value=7), min_size=1, max_size=8, unique=True
).map(sorted)


@given(
    file_size=st.integers(min_value=0, max_value=10_000_000),
    sender_ids=sender_ids_strategy,
)
def test_every_block_assigned_exactly_once(file_size: int, sender_ids: list[int]) -> None:
    total_blocks = calculate_block_count(file_size, FEC)
    senders = [SenderId(sender_id) for sender_id in sender_ids]

    assignments = derive_shard_assignments(total_blocks, senders, base_port=9000)

    assert sorted(assignment.shard_residue for assignment in assignments) == list(
        range(len(senders))
    )

    all_assigned = sorted(block for a in assignments for block in a.assigned_blocks)
    assert all_assigned == list(range(total_blocks))
