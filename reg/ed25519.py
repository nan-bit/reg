"""Ed25519 signatures (RFC 8032), in pure Python. **Layer A** — part of the record.

WHY THIS FILE EXISTS
---------------------
`reg.chain` signs one Ed25519 checkpoint per epoch (epic #313), and this project
adds no dependencies (AGENTS.md) — so there is no `cryptography` to reach for.
Ed25519 is deterministic by construction (RFC 8032 §5.1.6): the same seed and
message always produce the same signature, which is what "same seed, same
bytes" needs from a signature scheme. This is a straightforward transcription of
the RFC, tested against its §7.1 vectors in `tests/test_ed25519.py`. It is not a
novel implementation and not a place to be clever: any deviation from the RFC
here is a bug, and the vectors are what say so.

WHAT IT IS NOT
--------------
Not a general-purpose crypto library. It does exactly three things —
`public_key`, `sign`, `verify` — over 32-byte seeds, and refuses everything
else. `verify` returns a bool and never raises on malformed input: a bad
signature is `False`, not an exception, because callers check artifacts whose
bytes are attacker-controlled.
"""

from __future__ import annotations

import hashlib

__all__ = ["public_key", "seed_bytes", "sign", "verify"]

#: An Ed25519 seed (the private key) is 32 bytes. Anything else is refused.
SEED_BYTES = 32

#: Public keys and the `R` half of a signature are 32 bytes; a signature is 64.
PUBLIC_BYTES = 32
SIGNATURE_BYTES = 64

# Curve25519 field prime and the Ed25519 constants (RFC 8032 §5.1).
_P = 2**255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_L = 2**252 + 27742317777372353535851937790883648493


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _xrecover(y: int) -> int:
    """Recover the even x for a curve point with the given y (RFC 8032 §5.1.3)."""
    xx = (y * y - 1) * _inv(_D * y * y + 1) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * pow(2, (_P - 1) // 4, _P)) % _P
    if x % 2 != 0:
        x = _P - x
    return x


# The base point: y = 4/5, x the even root (RFC 8032 §5.1, Table 1).
_GY = (4 * _inv(5)) % _P
_GX = _xrecover(_GY)
_G = (_GX, _GY)


def _encode_int(y: int) -> bytes:
    return y.to_bytes(32, "little")


def _decode_int(data: bytes) -> int:
    return int.from_bytes(data, "little")


def _encode_point(point: tuple[int, int]) -> bytes:
    x, y = point
    bits = (x & 1) << 255
    return ((y & ((1 << 255) - 1)) | bits).to_bytes(32, "little")


def _decode_point(data: bytes) -> tuple[int, int] | None:
    """A curve point, or `None` for anything malformed. Never raises."""
    if len(data) != 32:
        return None
    y = _decode_int(data) & ((1 << 255) - 1)
    x = _xrecover(y)
    if (x & 1) != (data[31] >> 7):
        x = _P - x
    point = (x, y)
    # Reject points that are not on the curve or are of low order: RFC 8032
    # §5.1.3's `xrecover` always returns *a* point, so check the equation.
    if (-x * x + y * y - 1 - _D * x * x * y * y) % _P != 0:
        return None
    return point


def _edwards_add(p: tuple[int, int], q: tuple[int, int]) -> tuple[int, int]:
    # Twisted Edwards addition for a = -1 (RFC 8032 §5.1.4):
    #   x3 = (x1*y2 + x2*y1) / (1 + d*x1*x2*y1*y2)
    #   y3 = (y1*y2 + x1*x2) / (1 - d*x1*x2*y1*y2)
    # The plus in the y numerator is the a = -1 case (-a = +1); the a = +1
    # form has a minus there, and using it silently computes on the wrong
    # curve for most inputs.
    x1, y1 = p
    x2, y2 = q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _D * x1 * x2 * y1 * y2) % _P
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _D * x1 * x2 * y1 * y2) % _P
    return (x3, y3)


def _scalarmult(point: tuple[int, int], e: int) -> tuple[int, int]:
    """Scalar multiplication, double-and-add. Not constant-time.

    Timing side channels are out of scope here: signatures are made once per
    epoch at artifact close, on a build machine, not in a request path. Stated
    rather than fixed, so nobody deploys this where it matters without knowing.
    """
    result = (0, 1)  # the identity
    addend = point
    while e > 0:
        if e & 1:
            result = _edwards_add(result, addend)
        addend = _edwards_add(addend, addend)
        e >>= 1
    return result


def _clamp(h: bytes) -> int:
    """The secret scalar from the first half of SHA-512(seed) (RFC 8032 §5.1.5)."""
    a = 2**254 + sum(2**i * ((h[i // 8] >> (i % 8)) & 1) for i in range(3, 254))
    return a


def _require_seed(seed: bytes) -> bytes:
    if not isinstance(seed, bytes) or len(seed) != SEED_BYTES:
        raise ValueError(
            f"an Ed25519 seed is {SEED_BYTES} bytes, got "
            f"{type(seed).__name__} of length {len(seed) if isinstance(seed, bytes) else '?'}."
        )
    return seed


def public_key(seed: bytes) -> bytes:
    """The 32-byte public key for a 32-byte seed."""
    _require_seed(seed)
    a = _clamp(hashlib.sha512(seed).digest())
    return _encode_point(_scalarmult(_G, a))


def sign(seed: bytes, message: bytes) -> bytes:
    """Deterministic Ed25519 signature (RFC 8032 §5.1.6). 64 bytes.

    Deterministic in the RFC's sense: the nonce derives from the seed and the
    message, so the same seed and message always give the same signature —
    which is what makes epoch checkpoints reproducible byte-for-byte.
    """
    _require_seed(seed)
    if not isinstance(message, bytes):
        raise TypeError(f"sign takes bytes, got {type(message).__name__}.")
    h = hashlib.sha512(seed).digest()
    a = _clamp(h)
    prefix = h[32:]
    r = _decode_int(hashlib.sha512(prefix + message).digest()) % _L
    big_r = _encode_point(_scalarmult(_G, r))
    big_a = public_key(seed)
    k = _decode_int(hashlib.sha512(big_r + big_a + message).digest()) % _L
    s = (r + k * a) % _L
    return big_r + _encode_int(s)


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """True iff `signature` is a valid Ed25519 signature. Never raises.

    Malformed inputs — wrong lengths, a public key not on the curve, a bad `S`
    — are `False`. A verifier checking an artifact's bytes must not be able to
    turn a corrupt checkpoint into an exception that reads as a finding.
    """
    if (
        not isinstance(public, bytes)
        or not isinstance(message, bytes)
        or not isinstance(signature, bytes)
        or len(public) != PUBLIC_BYTES
        or len(signature) != SIGNATURE_BYTES
    ):
        return False
    a_point = _decode_point(public)
    if a_point is None:
        return False
    big_r = _decode_point(signature[:32])
    if big_r is None:
        return False
    s = _decode_int(signature[32:])
    if s >= _L:
        return False
    k = _decode_int(hashlib.sha512(signature[:32] + public + message).digest()) % _L
    # Check S*B == R + k*A.
    left = _scalarmult(_G, s)
    right = _edwards_add(big_r, _scalarmult(a_point, k))
    return left == right


def seed_bytes() -> int:
    """The seed length, for callers that size buffers. A function so the
    constant cannot drift from the check in `_require_seed` without the tests
    noticing — `tests/test_ed25519.py` asserts they agree."""
    return SEED_BYTES
