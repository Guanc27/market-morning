"""Tests for Keychain-backed OAuth token storage + plaintext migration.

The real `security` CLI is monkeypatched with an in-memory store so these run
without ever touching the login Keychain.
"""

import json

import pytest

from app import robinhood_mcp_oauth as rmo


@pytest.fixture
def fake_keychain(monkeypatch):
    store: dict[tuple[str, str], str] = {}

    def _get(service, account):
        return store.get((service, account))

    def _set(service, account, secret):
        store[(service, account)] = secret
        return True

    def _delete(service, account):
        return store.pop((service, account), None) is not None

    monkeypatch.setattr(rmo.keychain, "get_generic_password", _get)
    monkeypatch.setattr(rmo.keychain, "set_generic_password", _set)
    monkeypatch.setattr(rmo.keychain, "delete_generic_password", _delete)
    return store


def test_write_read_roundtrip(tmp_path, fake_keychain):
    storage = rmo.FileTokenStorage(path=tmp_path / "absent.json")
    storage._write({"tokens": {"access_token": "xyz"}})
    assert storage._read()["tokens"]["access_token"] == "xyz"
    assert storage.has_tokens() is True
    # Nothing was written to the plaintext path.
    assert not (tmp_path / "absent.json").exists()


def test_migrates_plaintext_into_keychain_then_deletes(tmp_path, fake_keychain):
    plaintext = tmp_path / "robinhood_mcp_oauth.json"
    plaintext.write_text(json.dumps({"tokens": {"access_token": "legacy-token"}}))

    storage = rmo.FileTokenStorage(path=plaintext)

    # Plaintext file is gone; token now lives in the (fake) Keychain.
    assert not plaintext.exists()
    assert fake_keychain[(rmo.KEYCHAIN_SERVICE, rmo.KEYCHAIN_ACCOUNT)]
    assert storage.has_tokens() is True
    assert storage._read()["tokens"]["access_token"] == "legacy-token"


def test_existing_keychain_wins_and_removes_stale_plaintext(tmp_path, fake_keychain):
    fake_keychain[(rmo.KEYCHAIN_SERVICE, rmo.KEYCHAIN_ACCOUNT)] = json.dumps(
        {"tokens": {"access_token": "keychain-token"}}
    )
    plaintext = tmp_path / "robinhood_mcp_oauth.json"
    plaintext.write_text(json.dumps({"tokens": {"access_token": "stale"}}))

    storage = rmo.FileTokenStorage(path=plaintext)

    assert not plaintext.exists()  # stale plaintext removed
    assert storage._read()["tokens"]["access_token"] == "keychain-token"


def test_no_tokens_when_empty(tmp_path, fake_keychain):
    storage = rmo.FileTokenStorage(path=tmp_path / "absent.json")
    assert storage.has_tokens() is False
    assert storage._read() == {}
