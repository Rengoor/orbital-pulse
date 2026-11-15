"""HMAC signing for the demo (shared key, stated as a limit); swap for asymmetric signatures later.

LIMIT: one shared secret (SIGNING_KEY) both signs and verifies, so anyone who
can verify a record can also forge one. Good enough to demonstrate tamper
evidence; a flight system would sign on board with a private key and verify on
the ground with the public key. This is demonstration key handling, not
flight-ready key management.

Every signed object names the key that signed it by ``key_id``, a fingerprint
that identifies the key without revealing it. The built-in demo key is
recognised and labelled wherever it is used.

Owner: person B
"""

from __future__ import annotations

import hashlib
import hmac
import os

_DEMO_SIGNING_KEY = "demo-only-change-me"


def default_signing_key() -> str:
    return os.environ.get("SIGNING_KEY", _DEMO_SIGNING_KEY)


def key_id(signing_key: str | None = None) -> str:
    """Public fingerprint of a signing key: safe to store and display."""
    key = signing_key if signing_key is not None else default_signing_key()
    return "k-" + hashlib.sha256(b"orbitalpulse-key-id:" + key.encode("utf-8")).hexdigest()[:16]


DEMO_KEY_ID = key_id(_DEMO_SIGNING_KEY)


def is_demo_key(signing_key: str | None = None) -> bool:
    """True when the key in use is the publicly known demonstration key."""
    return key_id(signing_key) == DEMO_KEY_ID


def require_signing_key(signing_key: str | None = None) -> str:
    """Return a non-demo signing key, or raise RuntimeError.

    Used at API startup so the server refuses to boot with an unset, empty, or
    demo signing key.
    """
    key = signing_key if signing_key is not None else os.environ.get("SIGNING_KEY")
    if not key or key == _DEMO_SIGNING_KEY:
        raise RuntimeError(
            "SIGNING_KEY must be set to a non-demo secret before starting the API"
        )
    return key


def sign(message: str, signing_key: str | None = None) -> str:
    """HMAC-SHA256 of *message* as a hex string."""
    key = signing_key if signing_key is not None else default_signing_key()
    return hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify(message: str, signature: str, signing_key: str | None = None) -> bool:
    """Constant-time check that *signature* is the HMAC of *message*."""
    if not isinstance(message, str) or not isinstance(signature, str):
        return False
    return hmac.compare_digest(sign(message, signing_key), signature)
