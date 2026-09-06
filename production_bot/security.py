from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def canonical_order(proposal: Any) -> bytes:
    payload = {
        "order_id": proposal.order_id,
        "account_id": proposal.account_id,
        "execution_environment": proposal.execution_environment,
        "symbol": proposal.symbol,
        "side": proposal.side,
        "quantity": _json_value(proposal.quantity),
        "order_type": proposal.order_type,
        "price": _json_value(proposal.price),
        "strategy_id": proposal.strategy_id,
        "strategy_version": proposal.strategy_version,
        "client_order_id": proposal.client_order_id,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def order_hash(proposal: Any) -> str:
    return hashlib.sha256(canonical_order(proposal)).hexdigest()


def approval_payload(order_digest: str, policy_version: str, nonce: str, expires_at: str) -> bytes:
    return f"{order_digest}|{policy_version}|{nonce}|{expires_at}".encode("utf-8")


def load_private_key(value: bytes) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(value, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("RISK_SIGNING_KEY_MUST_BE_ED25519")
    return key


def load_public_key(value: bytes) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(value)
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("EXECUTION_VERIFY_KEY_MUST_BE_ED25519")
    return key


def sign_approval(order_digest: str, policy_version: str, nonce: str, expires_at: str, signing_key: Ed25519PrivateKey) -> str:
    return signing_key.sign(approval_payload(order_digest, policy_version, nonce, expires_at)).hex()


def verify_approval(order_digest: str, policy_version: str, nonce: str, expires_at: str, signature: str, verification_key: Ed25519PublicKey) -> bool:
    try:
        verification_key.verify(bytes.fromhex(signature), approval_payload(order_digest, policy_version, nonce, expires_at))
        return True
    except (ValueError, TypeError):
        return False
