"""Backend-neutral encoder for YouTube's search filter parameter (`sp=`).

`sp` is a base64-encoded protobuf. Hum only needs three filters, all under
root field 2: type=Video (field 1), feature=Live (field 8), and the Music
topic (field 19). This tiny encoder covers exactly the wire types those use
(varint and length-delimited). Tests pin the output to the encodings YouTube's
own UI sends (captured from pytubefix 10.7.3 before it was removed).
"""
from __future__ import annotations

import base64

# YouTube's "Music" topic id (same value as youtube._MUSIC_TOPIC_ID).
MUSIC_TOPIC_ID = "/m/04rlf"

_WIRE_VARINT = 0
_WIRE_LEN = 2

Message = dict[int, "int | str | Message"]


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _encode(msg: Message) -> bytes:
    out = bytearray()
    for field, value in msg.items():
        if isinstance(value, bool) or not isinstance(value, (int, str, dict)):
            raise TypeError(f"unsupported protobuf value for field {field}: {value!r}")
        if isinstance(value, int):
            out += _varint((field << 3) | _WIRE_VARINT) + _varint(value)
        else:
            payload = value.encode() if isinstance(value, str) else _encode(value)
            out += _varint((field << 3) | _WIRE_LEN) + _varint(len(payload)) + payload
    return bytes(out)


def encode_message(msg: Message) -> str:
    """Encode a {field: int | str | nested} message to base64 (standard alphabet)."""
    return base64.b64encode(_encode(msg)).decode()


def build_search_sp(*, category: str | None, live: bool) -> str | None:
    """The `sp` value for Hum's search options, or None when unfiltered.

    Any filter implies type=Video; fields are emitted in ascending order.
    """
    if not category and not live:
        return None
    inner: Message = {1: 1}
    if live:
        inner[8] = 1
    if category == "music":
        inner[19] = MUSIC_TOPIC_ID
    return encode_message({2: dict(sorted(inner.items()))})
