"""Password hashing — one place, for the prompt-editor lock and for people.

Lifted out of `admin_gate` when sign-in arrived (`docs/17`), so the two cannot
drift: a cost raised in one and forgotten in the other is how an application
ends up with a strong lock on a side door and a weak one on the front.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

#: scrypt cost. n=2^15 lands around a tenth of a second on this class of
#: machine — slow enough to make guessing expensive, fast enough that nobody
#: notices signing in.
SCRYPT_N = 1 << 15
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 32

#: scrypt needs 128 * N * r bytes — 32 MiB at these parameters — and OpenSSL
#: refuses anything over its own 32 MiB default, so the shipped settings fail
#: by exactly the margin of the bookkeeping overhead. Raising the ceiling
#: rather than weakening the cost: this is a deliberate memory-hardness budget,
#: and lowering N to fit a default is the wrong half of the trade.
SCRYPT_MAXMEM = 128 * SCRYPT_N * SCRYPT_R * 2


@dataclass(frozen=True)
class Hashed:
    password_hash: bytes
    salt: bytes
    n: int
    r: int
    p: int


def derive(password: str, salt: bytes, *, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=KEY_LEN,
        maxmem=SCRYPT_MAXMEM,
    )


def hash_password(password: str) -> Hashed:
    salt = os.urandom(16)
    return Hashed(
        password_hash=derive(password, salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
    )


def matches(password: str, *, password_hash: bytes, salt: bytes, n: int, r: int, p: int) -> bool:
    """`compare_digest` rather than `==`, so a match costs the same as a miss."""
    candidate = derive(password, salt, n=n, r=r, p=p)
    return hmac.compare_digest(candidate, password_hash)


#: Hashed once at import and checked against when an email is unknown, so a
#: wrong address takes as long to refuse as a wrong password. Without it the
#: response time says which addresses have accounts.
_DECOY = hash_password(os.urandom(12).hex())


def burn_time(password: str) -> None:
    matches(
        password,
        password_hash=_DECOY.password_hash,
        salt=_DECOY.salt,
        n=_DECOY.n,
        r=_DECOY.r,
        p=_DECOY.p,
    )
