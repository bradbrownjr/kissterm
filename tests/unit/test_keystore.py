"""Saved logins in the OS keyring (kissterm/keystore.py, config.set_credential)."""

from __future__ import annotations

from kissterm._isolate import isolate

isolate()

import keyring  # noqa: E402
import pytest  # noqa: E402
from keyring.backend import KeyringBackend  # noqa: E402
from keyring.backends import fail  # noqa: E402

from kissterm import keystore  # noqa: E402
from kissterm.config import (  # noqa: E402
    Config,
    credential_store,
    find_credential,
    forget_credential,
    move_credentials_to_keyring,
    set_credential,
)


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        self.items.pop((service, username), None)


@pytest.fixture
def memory():
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(fail.Keyring())


def test_tests_never_see_the_real_keyring():
    assert isinstance(keyring.get_keyring(), fail.Keyring)
    assert not keystore.available()


def test_a_login_goes_to_the_keyring_and_config_keeps_only_its_name(memory):
    config = Config()
    assert set_credential(config, "Winlink KC1JMH", "s3cret") == "keyring"
    assert config.credentials == [{"name": "Winlink KC1JMH", "store": "keyring"}]
    assert memory.items[("kissterm", "Winlink KC1JMH")] == "s3cret"
    assert find_credential(config, "Winlink KC1JMH") == "s3cret"
    assert credential_store(config, "Winlink KC1JMH") == "keyring"


def test_a_rename_moves_it_and_forget_removes_it(memory):
    config = Config()
    set_credential(config, "BBS", "one")
    set_credential(config, "WS1EC BBS", "two", old_name="BBS")
    assert [c["name"] for c in config.credentials] == ["WS1EC BBS"]
    assert ("kissterm", "BBS") not in memory.items
    forget_credential(config, "WS1EC BBS")
    assert config.credentials == [] and memory.items == {}


def test_without_a_keyring_the_text_stays_in_config():
    config = Config()
    assert set_credential(config, "BBS", "pw") == "config"
    assert config.credentials == [{"name": "BBS", "text": "pw"}]
    assert find_credential(config, "BBS") == "pw" and credential_store(config, "BBS") == "config"
    assert move_credentials_to_keyring(config) == 0


def test_old_plain_text_logins_move_once(memory):
    config = Config()
    config.credentials = [{"name": "A", "text": "x"}, {"name": "B", "store": "keyring"}]
    assert move_credentials_to_keyring(config) == 1
    assert config.credentials[0] == {"name": "A", "store": "keyring"}
    assert move_credentials_to_keyring(config) == 0


def test_a_keyring_that_stops_answering_gives_no_text_not_a_crash(memory):
    config = Config()
    set_credential(config, "BBS", "pw")
    keyring.set_keyring(fail.Keyring())
    assert find_credential(config, "BBS") == ""
