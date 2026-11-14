"""HMAC signing for the demo (shared key, stated as a limit); swap for asymmetric signatures later.

LIMIT: one shared secret (SIGNING_KEY) both signs and verifies, so anyone who
can verify a record can also forge one. Good enough to demonstrate tamper
evidence; a flight system would sign on board with a private key and verify on
the ground with the public key.

Owner: person B
"""

from __future__ import annotations

import hashlib
import hmac
import os

_DEMO_SIGNING_KEY = "demo-only-change-me"


def default_signing_key() -> str:
    return os.environ.get("SIGNING_KEY", _DEMO_SIGNING_KEY)


def sign(message: str, signing_key: str | None = None) -> str:
    """HMAC-SHA256 of *message* as a hex string."""
    key = signing_key if signing_key is not None else default_signing_key()
    return hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify(message: str, signature: str, signing_key: str | None = None) -> bool:
    """Constant-time check that *signature* is the HMAC of *message*."""
    if not isinstance(message, str) or not isinstance(signature, str):
        return False
    return hmac.compare_digest(sign(message, signing_key), signature)
