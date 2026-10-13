import secrets
from collections.abc import Container

ID_LENGTH = 4
_ATTEMPTS_PER_LENGTH = 32


def new_id(taken: Container[str]) -> str:
    """A short hex ID not in `taken`, growing longer only if the short ones run out."""
    length = ID_LENGTH
    while True:
        for _ in range(_ATTEMPTS_PER_LENGTH):
            candidate = secrets.token_hex(length)[:length]
            if candidate not in taken:
                return candidate
        length += 1
