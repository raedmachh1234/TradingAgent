"""Operator signatures (Ed25519).

The operator's private key signs three kinds of thing: autonomy grants (the only way a strategy can run
above M1), operator commands (releasing the kill switch, clearing a downgrade) and, on the CLI channel,
individual approvals. The running bot only ever holds the public key, so it can verify but cannot sign.
Private-key functions live here and are used by the command-line tool only.
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ..core.types import canonical_json


# ---- keys -----------------------------------------------------------------------------------------
def generate_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def public_bytes(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def fingerprint(key: Ed25519PublicKey) -> str:
    return hashlib.sha256(public_bytes(key)).hexdigest()


def save_private_key(key: Ed25519PrivateKey, path: Path | str, passphrase: str | None = None) -> None:
    enc = serialization.BestAvailableEncryption(passphrase.encode("utf-8")) if passphrase else serialization.NoEncryption()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(pem)
    try:
        p.chmod(0o600)
    except OSError:
        pass


def load_private_key(path: Path | str, passphrase: str | None = None) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), passphrase.encode("utf-8") if passphrase else None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("operator key must be an Ed25519 private key")
    return key


def save_public_key(key: Ed25519PublicKey, path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(base64.b64encode(public_bytes(key)).decode("ascii") + "\n", encoding="ascii")


def load_public_key(path: Path | str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(Path(path).read_text(encoding="ascii").strip()))


# ---- generic payload signatures ---------------------------------------------------------------------
def sign_payload(private_key: Ed25519PrivateKey, payload: Any) -> str:
    return base64.b64encode(private_key.sign(canonical_json(payload).encode("utf-8"))).decode("ascii")


def verify_payload(public_key: Ed25519PublicKey | None, payload: Any, signature: str) -> bool:
    if public_key is None or not signature:
        return False
    try:
        public_key.verify(base64.b64decode(signature), canonical_json(payload).encode("utf-8"))
        return True
    except (InvalidSignature, ValueError):
        return False


# ---- autonomy grants --------------------------------------------------------------------------------
def grants_payload(doc: Mapping[str, Any]) -> dict[str, Any]:
    return {"version": doc.get("version", 1), "grants": doc.get("grants", [])}


def sign_grants(doc: Mapping[str, Any], private_key: Ed25519PrivateKey) -> dict[str, Any]:
    out = dict(grants_payload(doc))
    out["key_id"] = fingerprint(private_key.public_key())
    out["signature"] = sign_payload(private_key, grants_payload(doc))
    return out


def verify_grants(doc: Mapping[str, Any], public_key: Ed25519PublicKey | None) -> bool:
    return verify_payload(public_key, grants_payload(doc), str(doc.get("signature", "")))


# ---- operator commands ------------------------------------------------------------------------------
@dataclass(frozen=True)
class OperatorCommand:
    action: str        # release_kill_switch | clear_downgrade
    scope: str         # "global" or a strategy id
    issued_at: datetime
    nonce: str
    signature: str = ""

    def payload(self) -> dict[str, Any]:
        return {"action": self.action, "scope": self.scope, "issued_at": self.issued_at, "nonce": self.nonce}


def sign_command(private_key: Ed25519PrivateKey, action: str, scope: str, issued_at: datetime, nonce: str) -> OperatorCommand:
    cmd = OperatorCommand(action, scope, issued_at, nonce)
    return OperatorCommand(action, scope, issued_at, nonce, sign_payload(private_key, cmd.payload()))


class CommandVerifier:
    """Verifies operator commands: right signature, recent, and never seen before."""

    def __init__(self, public_key: Ed25519PublicKey | None, max_age_seconds: float = 300.0) -> None:
        self.public_key, self.max_age = public_key, max_age_seconds
        self._seen: set[str] = set()

    def verify(self, cmd: OperatorCommand, action: str, now: datetime) -> tuple[bool, str]:
        if cmd.action != action:
            return False, f"command is {cmd.action!r}, expected {action!r}"
        if not verify_payload(self.public_key, cmd.payload(), cmd.signature):
            return False, "signature does not verify against the operator public key"
        if abs((now - cmd.issued_at).total_seconds()) > self.max_age:
            return False, "command is too old"
        if cmd.nonce in self._seen:
            return False, "command was already used"
        self._seen.add(cmd.nonce)
        return True, "ok"
