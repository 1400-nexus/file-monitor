from pathlib import Path

import blake3
import pytest

from file_monitor.domain.ids import SenderId
from file_monitor.ipc.errors import ProtoHashMismatchError
from file_monitor.ipc.handshake import (
    canonicalize_proto_text,
    compute_proto_hash,
    verify_proto_hash,
)

REPO_PROTO_DIR = Path(__file__).resolve().parents[2] / "libs" / "nexus-proto" / "proto"


def test_canonicalize_strips_line_comments() -> None:
    text = "message Foo {\n  int32 bar = 1; // a trailing comment\n}\n"
    canonical = canonicalize_proto_text(text)
    assert "//" not in canonical
    assert "trailing" not in canonical


def test_canonicalize_strips_block_comments() -> None:
    text = "message Foo {\n/* a\nblock comment */\n  int32 bar = 1;\n}\n"
    canonical = canonicalize_proto_text(text)
    assert "block" not in canonical
    assert "comment" not in canonical


def test_canonicalize_collapses_whitespace_differences() -> None:
    spaced = "message   Foo{\n\tint32 bar=1;\n}"
    compact = "message Foo{ int32 bar=1; }"
    assert canonicalize_proto_text(spaced) == canonicalize_proto_text(compact)


def test_compute_proto_hash_is_stable_across_comment_only_edits(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    (dir_a / "foo.proto").write_text("message Foo { int32 bar = 1; }\n")

    dir_b = tmp_path / "b"
    dir_b.mkdir()
    (dir_b / "foo.proto").write_text(
        "// a helpful comment\nmessage Foo {\n  int32 bar = 1; // inline\n}\n"
    )

    assert compute_proto_hash(dir_a) == compute_proto_hash(dir_b)


def test_compute_proto_hash_changes_when_contract_changes(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    (dir_a / "foo.proto").write_text("message Foo { int32 bar = 1; }\n")

    dir_b = tmp_path / "b"
    dir_b.mkdir()
    (dir_b / "foo.proto").write_text("message Foo { int32 bar = 2; }\n")

    assert compute_proto_hash(dir_a) != compute_proto_hash(dir_b)


def test_compute_proto_hash_is_a_blake3_digest(tmp_path: Path) -> None:
    (tmp_path / "foo.proto").write_text("message Foo {}\n")
    assert len(compute_proto_hash(tmp_path)) == blake3.blake3().digest_size


def test_compute_proto_hash_against_the_real_contract() -> None:
    digest = compute_proto_hash(REPO_PROTO_DIR)
    assert len(digest) == blake3.blake3().digest_size


def test_verify_proto_hash_accepts_a_match() -> None:
    verify_proto_hash(SenderId(1), b"abc", b"abc")


def test_verify_proto_hash_rejects_a_mismatch() -> None:
    with pytest.raises(ProtoHashMismatchError):
        verify_proto_hash(SenderId(1), b"abc", b"xyz")
