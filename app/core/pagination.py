import base64
import binascii
import math

from fastapi import HTTPException, status


def encode_cursor(last_id: int) -> str:
    return base64.urlsafe_b64encode(f"id:{last_id}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        prefix, _, value = raw.partition(":")
        if prefix != "id":
            raise ValueError
        return int(value)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor") from None


def total_pages(total: int, limit: int) -> int:
    return math.ceil(total / limit) if total else 0
