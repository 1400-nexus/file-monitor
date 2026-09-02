from file_monitor.domain.ids import SenderId


class HandshakeError(Exception):
    def __init__(self, field_name: str) -> None:
        super().__init__(f"expected sender_hello, got {field_name}")
        self.field_name = field_name


class UnknownSenderError(KeyError):
    def __init__(self, sender_id: SenderId) -> None:
        super().__init__(f"no connected peer for sender_id {sender_id}")
        self.sender_id = sender_id
