import re

RECV_BUFFER_BYTES = 65536
SEND_QUEUE_MAXSIZE = 64

LINE_COMMENT_PATTERN = re.compile(r"//[^\n]*")
BLOCK_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
WHITESPACE_PATTERN = re.compile(r"\s+")

ENVELOPE_ONEOF_GROUP_NAME = "msg"
SENDER_HELLO_FIELD_NAME = "sender_hello"
