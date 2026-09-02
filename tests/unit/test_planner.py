import re
from pathlib import Path

from file_monitor.domain.models import FecParams, SourceFile
from file_monitor.services.constants import SESSION_ID_RANDOM_BYTES, UNSET_SENDER_BPS_LIMIT
from file_monitor.services.planner import build_manifest, encode_shard_key, generate_session_id

SESSION_ID_HEX_PATTERN = re.compile(r"^[0-9a-f]+$")


def test_generate_session_id_is_lowercase_hex_of_expected_length() -> None:
    session_id = generate_session_id()
    assert len(session_id) == SESSION_ID_RANDOM_BYTES * 2
    assert SESSION_ID_HEX_PATTERN.match(session_id)


def test_generate_session_id_is_not_deterministic() -> None:
    assert generate_session_id() != generate_session_id()


def test_encode_shard_key_is_identity_today() -> None:
    for index in range(5):
        assert encode_shard_key(index) == index


def test_build_manifest_populates_fields_from_source_file_and_fec_params() -> None:
    source_file = SourceFile(
        path=Path("/watch/example.bin"), size_bytes=280_001, file_hash="ab" * 32
    )
    fec_params = FecParams(k=200, n=255, symbol_bytes=1400)

    manifest = build_manifest(
        source_file, fec_params, session_id="0123456789abcdef", sender_index=2
    )

    assert manifest.session_id == "0123456789abcdef"
    assert manifest.filepath == str(source_file.path)
    assert manifest.file_size == 280_001
    assert manifest.file_hash == bytes.fromhex("ab" * 32)
    assert manifest.k == 200
    assert manifest.n == 255
    assert manifest.block_bytes == fec_params.symbol_bytes
    assert manifest.total_blocks == 2
    assert manifest.sender_id == 2
    assert manifest.sender_bps_limit == UNSET_SENDER_BPS_LIMIT


def test_build_manifest_accepts_an_explicit_sender_bps_limit() -> None:
    source_file = SourceFile(path=Path("/watch/x.bin"), size_bytes=10, file_hash="00" * 32)
    fec_params = FecParams(k=4, n=6, symbol_bytes=10)

    manifest = build_manifest(
        source_file, fec_params, session_id="0" * 16, sender_index=0, sender_bps_limit=5_000_000
    )

    assert manifest.sender_bps_limit == 5_000_000
