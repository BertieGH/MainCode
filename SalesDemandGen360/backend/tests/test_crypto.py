"""Credential handling — the three rules from CLAUDE.md, as tests.

The leak tests matter more than the round-trip test. Encryption failing is
obvious; a key reaching a log line is invisible until someone reads the logs.
"""

from __future__ import annotations

import logging

import pytest

from app.services.crypto import (
    CredentialError,
    SecretValue,
    decrypt,
    encrypt,
    last_four,
)

API_KEY = "sk-ant-api03-EXAMPLE-NOT-REAL-abcdefgh1234"


class TestRoundTrip:
    def test_encrypt_then_decrypt_returns_the_value(self):
        assert decrypt(encrypt(API_KEY)).reveal() == API_KEY

    def test_ciphertext_does_not_contain_the_plaintext(self):
        blob = encrypt(API_KEY)
        assert API_KEY.encode() not in blob
        assert b"sk-ant" not in blob

    def test_encryption_is_non_deterministic(self):
        """Two encryptions of the same value must differ.

        Deterministic ciphertext would let anyone with read access to the table
        tell which providers share a key.
        """
        assert encrypt(API_KEY) != encrypt(API_KEY)

    def test_empty_credential_is_refused(self):
        with pytest.raises(ValueError):
            encrypt("")

    def test_wrong_key_raises_without_leaking(self, monkeypatch):
        blob = encrypt(API_KEY)
        from app.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("SECRET_KEY", "a-completely-different-secret-key")
        with pytest.raises(CredentialError) as exc:
            decrypt(blob)
        assert "sk-ant" not in str(exc.value)
        get_settings.cache_clear()


class TestSecretValueRefusesToLeak:
    def test_str_is_redacted(self):
        assert str(SecretValue(API_KEY)) == "<redacted>"

    def test_repr_is_redacted(self):
        assert "sk-ant" not in repr(SecretValue(API_KEY))

    def test_fstring_is_redacted(self):
        """The most likely accident: someone interpolates it into a message."""
        assert "sk-ant" not in f"key={SecretValue(API_KEY)}"

    def test_percent_format_is_redacted(self):
        assert "sk-ant" not in "key=%s" % (SecretValue(API_KEY),)  # noqa: UP031 - the % path is what is under test

    def test_logging_does_not_emit_the_value(self, caplog):
        with caplog.at_level(logging.INFO):
            logging.getLogger("test").info("using %s", SecretValue(API_KEY))
        assert "sk-ant" not in caplog.text
        assert "<redacted>" in caplog.text

    def test_reveal_is_the_only_way_out(self):
        assert SecretValue(API_KEY).reveal() == API_KEY


class TestLastFour:
    def test_returns_final_four(self):
        assert last_four(API_KEY) == "1234"

    def test_short_value_returns_empty_rather_than_the_whole_thing(self):
        """A 3-character secret must not be returned in full as its own hint."""
        assert last_four("abc") == ""

    def test_secret_value_exposes_last_four(self):
        assert SecretValue(API_KEY).last_four == "1234"
