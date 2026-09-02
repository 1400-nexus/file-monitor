from file_monitor.domain.ids import SenderId


class HandshakeError(Exception):
    def __init__(self, field_name: str) -> None:
        super().__init__(f"expected sender_hello, got {field_name}")
        self.field_name: str = field_name


class UnknownSenderError(KeyError):
    def __init__(self, sender_id: SenderId) -> None:
        super().__init__(f"no connected peer for sender_id {sender_id}")
        self.sender_id: SenderId = sender_id


class ProtoHashMismatchError(Exception):
    def __init__(self, sender_id: SenderId, reported_hash: bytes, expected_hash: bytes) -> None:
        super().__init__(
            f"sender_id {sender_id} reported proto_hash {reported_hash.hex()}, "
            f"expected {expected_hash.hex()}"
        )
        self.sender_id: SenderId = sender_id
        self.reported_hash: bytes = reported_hash
        self.expected_hash: bytes = expected_hash


class SendQueueFullError(Exception):
    def __init__(self, sender_id: SenderId) -> None:
        super().__init__(f"send queue full for sender_id {sender_id}")
        self.sender_id: SenderId = sender_id
