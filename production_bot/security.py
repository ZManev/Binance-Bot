from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def canonical_order(proposal: Any) -> bytes:
    payload = {
        "order_id": proposal.order_id,
        "account_id": proposal.account_id,
        "symbol": proposal.symbol,
        "side": proposal.side,
        "quantity": _json_value(proposal.quantity),
        "order_type": proposal.order_type,
        "price": _json_value(proposal.price),
        "strategy_id": proposal.strategy_id,
        "strategy_version": proposal.strategy_version,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def order_hash(proposal: Any) -> str:
    return hashlib.sha256(canonical_order(proposal)).hexdigest()


def approval_payload(order_digest: str, policy_version: str, nonce: str, expires_at: str) -> bytes:
    return f"{order_digest}|{policy_version}|{nonce}|{expires_at}".encode()


def sign_approval(order_digest: str, policy_version: str, nonce: str, expires_at: str, signing_secret: bytes) -> str:
    payload = approval_payload(order_digest, policy_version, nonce, expires_at)
    return hmac.new(signing_secret, payload, hashlib.sha256).hexdigest()


def verify_approval(order_digest: str, policy_version: str, nonce: str, expires_at: str, signature: str, signing_secret: bytes) -> bool:
    expected = sign_approval(order_digest, policy_version, nonce, expires_at, signing_secret)
    return hmac.compare_digest(expected, signature)
