"""Operator keys, grant signatures and command verification."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from quantbot.execution import signing

from conftest import T0


def test_key_round_trip_with_and_without_passphrase(tmp_path):
    k = signing.generate_private_key()
    signing.save_private_key(k, tmp_path / "op.key", "correct horse")
    signing.save_public_key(k.public_key(), tmp_path / "op.pub")
    loaded = signing.load_private_key(tmp_path / "op.key", "correct horse")
    assert signing.fingerprint(loaded.public_key()) == signing.fingerprint(signing.load_public_key(tmp_path / "op.pub"))
    with pytest.raises(ValueError):
        signing.load_private_key(tmp_path / "op.key", "wrong")
    signing.save_private_key(k, tmp_path / "plain.key")
    assert signing.fingerprint(signing.load_private_key(tmp_path / "plain.key").public_key()) == signing.fingerprint(k.public_key())


def test_grant_signatures_cover_every_field():
    k = signing.generate_private_key()
    doc = signing.sign_grants({"version": 1, "grants": [{"strategy": "s1", "max_mode": "M2", "signed_at": "2026-01-01"}]}, k)
    assert signing.verify_grants(doc, k.public_key())
    assert not signing.verify_grants(doc, signing.generate_private_key().public_key())
    for field, value in (("strategy", "s2"), ("max_mode", "M3"), ("signed_at", "2020-01-01")):
        bad = {**doc, "grants": [{**doc["grants"][0], field: value}]}
        assert not signing.verify_grants(bad, k.public_key()), field
    assert not signing.verify_grants({**doc, "version": 2}, k.public_key())
    assert not signing.verify_grants({**doc, "signature": ""}, k.public_key())
    assert not signing.verify_grants(doc, None)


def test_command_verifier_checks_signature_action_age_and_reuse():
    k = signing.generate_private_key()
    v = signing.CommandVerifier(k.public_key(), max_age_seconds=300)
    cmd = signing.sign_command(k, "clear_downgrade", "global", T0, uuid.uuid4().hex)
    assert v.verify(cmd, "release_kill_switch", T0) == (False, "command is 'clear_downgrade', expected 'release_kill_switch'")
    assert not v.verify(cmd, "clear_downgrade", T0 + timedelta(seconds=301))[0]
    assert v.verify(cmd, "clear_downgrade", T0) == (True, "ok")
    assert v.verify(cmd, "clear_downgrade", T0)[1] == "command was already used"
    forged = signing.sign_command(signing.generate_private_key(), "clear_downgrade", "global", T0, uuid.uuid4().hex)
    assert not v.verify(forged, "clear_downgrade", T0)[0]
    assert not signing.CommandVerifier(None).verify(cmd, "clear_downgrade", T0)[0]
