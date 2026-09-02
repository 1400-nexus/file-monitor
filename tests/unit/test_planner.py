import re
from pathlib import Path

import common_pb2
import pytest

from file_monitor.domain.models import FecParams, SourceFile
from file_monitor.services.constants import SESSION_ID_RANDOM_BYTES, UNSET_SENDER_BPS_LIMIT
from file_monitor.services.planner import (
    apply_shard,
    build_assign_session,
    build_manifest,
    generate_session_id,
)

SESSION_ID_HEX_PATTERN = re.compile(r"^[0-9a-f]+$")
VALID_FILE_HASH = "ab" * 32
WATCH_ROOT = Path("/watch")
ONE_BYTE_BLOCK_FEC = FecParams(k=1, n=1, symbol_bytes=1)


def make_source_file(
    *, relative_path: str = "example.bin", size_bytes: int = 10, file_hash: str = VALID_FILE_HASH
) -> SourceFile:
    return SourceFile(path=WATCH_ROOT / relative_path, size_bytes=size_bytes, file_hash=file_hash)


def test_generate_session_id_is_lowercase_hex_of_expected_length() -> None:
    session_id = generate_session_id()
    assert len(session_id) == SESSION_ID_RANDOM_BYTES * 2
    assert SESSION_ID_HEX_PATTERN.match(session_id)


def test_generate_session_id_is_not_deterministic() -> None:
    assert generate_session_id() != generate_session_id()


def test_apply_shard_sets_sender_id_to_the_residue_not_a_process_identity() -> None:
    manifest = common_pb2.Manifest()
    apply_shard(manifest, sender_index=2, shard_modulus=3)
    assert manifest.sender_id == 2


def test_apply_shard_rejects_out_of_range_sender_index() -> None:
    manifest = common_pb2.Manifest()
    with pytest.raises(ValueError, match="sender_index"):
        apply_shard(manifest, sender_index=7, shard_modulus=3)


def test_apply_shard_rejects_non_positive_modulus() -> None:
    manifest = common_pb2.Manifest()
    with pytest.raises(ValueError, match="shard_modulus"):
        apply_shard(manifest, sender_index=0, shard_modulus=0)


def test_build_manifest_wire_contract_shards_are_disjoint_and_cover_every_block() -> None:
    source_file = make_source_file(size_bytes=10)
    shard_modulus = 3

    block_sets = []
    for sender_index in range(shard_modulus):
        manifest = build_manifest(
            source_file,
            ONE_BYTE_BLOCK_FEC,
            session_id=generate_session_id(),
            sender_index=sender_index,
            shard_modulus=shard_modulus,
            watch_root=WATCH_ROOT,
        )
        assert manifest.total_blocks == 10
        block_sets.append(
            {b for b in range(manifest.total_blocks) if b % shard_modulus == manifest.sender_id}
        )

    assert block_sets[0].isdisjoint(block_sets[1])
    assert block_sets[0].isdisjoint(block_sets[2])
    assert block_sets[1].isdisjoint(block_sets[2])
    assert block_sets[0] | block_sets[1] | block_sets[2] == set(range(10))


def test_build_manifest_populates_fields() -> None:
    source_file = make_source_file(relative_path="sub/example.bin", size_bytes=10)

    manifest = build_manifest(
        source_file,
        ONE_BYTE_BLOCK_FEC,
        session_id="0123456789abcdef",
        sender_index=1,
        shard_modulus=3,
        watch_root=WATCH_ROOT,
    )

    assert manifest.session_id == "0123456789abcdef"
    assert manifest.filepath == "sub/example.bin"
    assert not Path(manifest.filepath).is_absolute()
    assert manifest.file_size == 10
    assert manifest.file_hash == bytes.fromhex(VALID_FILE_HASH)
    assert manifest.k == 1
    assert manifest.n == 1
    assert manifest.block_bytes == 1
    assert manifest.total_blocks == 10
    assert manifest.sender_id == 1
    assert manifest.sender_bps_limit == UNSET_SENDER_BPS_LIMIT


def test_build_manifest_accepts_an_explicit_sender_bps_limit() -> None:
    source_file = make_source_file()

    manifest = build_manifest(
        source_file,
        ONE_BYTE_BLOCK_FEC,
        session_id="0" * 16,
        sender_index=0,
        shard_modulus=1,
        watch_root=WATCH_ROOT,
        sender_bps_limit=5_000_000,
    )

    assert manifest.sender_bps_limit == 5_000_000


def test_build_manifest_rejects_out_of_range_sender_index() -> None:
    source_file = make_source_file()
    with pytest.raises(ValueError, match="sender_index"):
        build_manifest(
            source_file,
            ONE_BYTE_BLOCK_FEC,
            session_id="0" * 16,
            sender_index=7,
            shard_modulus=3,
            watch_root=WATCH_ROOT,
        )


def test_build_manifest_rejects_non_positive_shard_modulus() -> None:
    source_file = make_source_file()
    with pytest.raises(ValueError, match="shard_modulus"):
        build_manifest(
            source_file,
            ONE_BYTE_BLOCK_FEC,
            session_id="0" * 16,
            sender_index=0,
            shard_modulus=0,
            watch_root=WATCH_ROOT,
        )


def test_build_manifest_rejects_negative_size_bytes() -> None:
    source_file = make_source_file(size_bytes=-1)
    with pytest.raises(ValueError, match="size_bytes"):
        build_manifest(
            source_file,
            ONE_BYTE_BLOCK_FEC,
            session_id="0" * 16,
            sender_index=0,
            shard_modulus=1,
            watch_root=WATCH_ROOT,
        )


def test_build_manifest_rejects_wrong_length_file_hash() -> None:
    source_file = make_source_file(file_hash="ab" * 16)
    with pytest.raises(ValueError, match="file_hash"):
        build_manifest(
            source_file,
            ONE_BYTE_BLOCK_FEC,
            session_id="0" * 16,
            sender_index=0,
            shard_modulus=1,
            watch_root=WATCH_ROOT,
        )


def test_build_manifest_rejects_non_hex_file_hash() -> None:
    source_file = make_source_file(file_hash="zz" * 32)
    with pytest.raises(ValueError, match="file_hash"):
        build_manifest(
            source_file,
            ONE_BYTE_BLOCK_FEC,
            session_id="0" * 16,
            sender_index=0,
            shard_modulus=1,
            watch_root=WATCH_ROOT,
        )


def test_build_manifest_rejects_a_path_outside_watch_root() -> None:
    source_file = SourceFile(
        path=Path("/elsewhere/example.bin"), size_bytes=10, file_hash=VALID_FILE_HASH
    )
    with pytest.raises(ValueError, match="watch_root"):
        build_manifest(
            source_file,
            ONE_BYTE_BLOCK_FEC,
            session_id="0" * 16,
            sender_index=0,
            shard_modulus=1,
            watch_root=WATCH_ROOT,
        )


def test_build_assign_session_carries_modulus_as_total_senders() -> None:
    manifest = common_pb2.Manifest(session_id="abc")
    assign_session = build_assign_session(
        manifest, shard_modulus=3, target_host="10.0.0.5", target_port=9002
    )
    assert assign_session.manifest == manifest
    assert assign_session.total_senders == 3
    assert assign_session.target_host == "10.0.0.5"
    assert assign_session.target_port == 9002
