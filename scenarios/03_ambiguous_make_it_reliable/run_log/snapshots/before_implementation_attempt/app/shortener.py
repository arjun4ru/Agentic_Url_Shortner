"""Base62 short-code generation.

Codes are derived from an atomic, monotonically increasing counter rather
than random generation + collision retries: this guarantees uniqueness by
construction and keeps generation O(1) with no retry loop.
"""

import string

_ALPHABET = string.digits + string.ascii_lowercase + string.ascii_uppercase
_BASE = len(_ALPHABET)
_OFFSET = 100_000  # avoids confusingly short codes ("0", "1", ...) for the first links


def encode_base62(number: int) -> str:
    if number == 0:
        return _ALPHABET[0]
    digits = []
    n = number
    while n > 0:
        n, remainder = divmod(n, _BASE)
        digits.append(_ALPHABET[remainder])
    return "".join(reversed(digits))


def generate_short_code(counter_value: int) -> str:
    return encode_base62(counter_value + _OFFSET)
