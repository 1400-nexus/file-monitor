import ipc_pb2
import pytest

from file_monitor.ipc.codec import decode, encode


def test_encode_decode_round_trip_sender_hello() -> None:
    original = ipc_pb2.SenderHello(sender_id=3, pid=1234, proto_hash=b"abc")
    field_name, decoded = decode(encode(original))
    assert field_name == "sender_hello"
    assert decoded == original


def test_encode_decode_round_trip_assign_session() -> None:
    original = ipc_pb2.AssignSession(total_senders=3, target_host="10.0.0.1", target_port=9000)
    field_name, decoded = decode(encode(original))
    assert field_name == "assign_session"
    assert decoded == original


def test_encode_decode_round_trip_heartbeat() -> None:
    original = ipc_pb2.Heartbeat(process_id=42, timestamp_unix_ms=1_700_000_000_000)
    field_name, decoded = decode(encode(original))
    assert field_name == "heartbeat"
    assert decoded == original


def test_decode_rejects_envelope_with_no_message_set() -> None:
    empty_envelope = ipc_pb2.Envelope()
    with pytest.raises(ValueError, match="Envelope has no message set"):
        decode(empty_envelope.SerializeToString())
