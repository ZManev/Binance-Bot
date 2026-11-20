from dataclasses import asdict
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .production_boundary import (
    ApprovalClaims, ApprovalVerifier, BoundaryBlocked, DurableBoundaryStore,
    ExecutionFlags, FileKillSwitch, ProductionExecutionBoundary,
)


def claims():
    return ApprovalClaims(
        approval_id="ap-1", order_id="ord-1", order_hash="a" * 64,
        account_id="acct-1", exchange="binance", environment="production",
        symbol="BTCUSDT", side="BUY", quantity="0.001",
        approved_notional="100", policy_version="risk-v1",
        nonce="nonce-1", issued_at=1000, expires_at=1010,
    )


def keys():
    private = Ed25519PrivateKey.generate()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, public_pem


def test_execution_flags_reject_any_live_switch():
    assert ExecutionFlags.from_env({"LIVE_TRADING": "false"}).live_trading is False
    with pytest.raises(BoundaryBlocked, match="LIVE_EXECUTION_FEATURES_MUST_REMAIN_DISABLED"):
        ExecutionFlags.from_env({"LIVE_TRADING": "true"})
    with pytest.raises(BoundaryBlocked, match="LIVE_EXECUTION_FEATURES_MUST_REMAIN_DISABLED"):
        ExecutionFlags.from_env({"SIGNING_ENABLED": "true"})
    with pytest.raises(BoundaryBlocked, match="LIVE_EXECUTION_FEATURES_MUST_REMAIN_DISABLED"):
        ExecutionFlags.from_env({"ORDER_SUBMISSION_ENABLED": "true"})


def test_external_ed25519_approval_is_verified():
    private, public_pem = keys()
    c = claims()
    signature = private.sign(c.canonical()).hex()
    ApprovalVerifier(public_pem).verify(c, signature, now=1005)
    with pytest.raises(BoundaryBlocked, match="INVALID_RISK_AUTHORITY_SIGNATURE"):
        ApprovalVerifier(public_pem).verify(c, "00", now=1005)


def test_expired_or_long_ttl_approval_is_rejected():
    private, public_pem = keys()
    c = claims()
    sig = private.sign(c.canonical()).hex()
    with pytest.raises(BoundaryBlocked, match="APPROVAL_EXPIRED_OR_NOT_YET_VALID"):
        ApprovalVerifier(public_pem).verify(c, sig, now=1010)
    long_claim = ApprovalClaims(**{**asdict(c), "expires_at": 1020})
    long_sig = private.sign(long_claim.canonical()).hex()
    with pytest.raises(BoundaryBlocked, match="APPROVAL_TTL_EXCEEDED"):
        ApprovalVerifier(public_pem).verify(long_claim, long_sig, now=1005)


def test_reservation_rejects_order_and_nonce_replay(tmp_path):
    store = DurableBoundaryStore(str(tmp_path / "state.sqlite"))
    c = claims()
    store.reserve(c, now=1001)
    with pytest.raises(BoundaryBlocked, match="ORDER_OR_APPROVAL_NONCE_REPLAY"):
        store.reserve(c, now=1002)
    store.close()


def test_state_machine_forbids_unknown_retry(tmp_path):
    store = DurableBoundaryStore(str(tmp_path / "state.sqlite"))
    c = claims()
    store.reserve(c, now=1001)
    store.transition(c.order_id, "SUBMITTING", now=1002)
    store.transition(c.order_id, "UNKNOWN", now=1003)
    with pytest.raises(BoundaryBlocked, match="INVALID_EXECUTION_STATE_TRANSITION"):
        store.transition(c.order_id, "SUBMITTING", now=1004)
    store.transition(c.order_id, "RECONCILED", now=1005)
    store.close()


def test_persistent_audit_chain_verifies_and_survives_reopen(tmp_path):
    path = str(tmp_path / "audit.sqlite")
    store = DurableBoundaryStore(path)
    store.append_audit("APPROVAL_VERIFIED", {"order_id": "ord-1"}, now=1001)
    store.append_audit("SIMULATION_ONLY", {"order_id": "ord-1"}, now=1002)
    assert store.verify_audit()
    store.close()
    reopened = DurableBoundaryStore(path)
    assert reopened.verify_audit()
    reopened.close()


def test_kill_switch_blocks_simulation_authorization(tmp_path):
    private, public_pem = keys()
    switch_path = tmp_path / "KILL"
    switch_path.write_text("HALT")
    store = DurableBoundaryStore(str(tmp_path / "state.sqlite"))
    boundary = ProductionExecutionBoundary(
        ExecutionFlags(), ApprovalVerifier(public_pem), store,
        FileKillSwitch(str(switch_path)),
    )
    c = claims()
    sig = private.sign(c.canonical()).hex()
    with pytest.raises(BoundaryBlocked, match="KILL_SWITCH_ACTIVE"):
        boundary.authorize_for_simulation(c, sig, now=1005)
    store.close()
