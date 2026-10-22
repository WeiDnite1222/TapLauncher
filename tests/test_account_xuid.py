import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core_lib.common.exception import ArgumentValueError, AuthenticationException
from core_lib.game import authentication
from core_lib.game.account import Account, convert_account_data_to_object, create_account, get_account_sample
from core_lib.game.argument import ArgumentMappings, generate_launch_command, replace_placeholders
from manager import account as account_module
from manager.account import AccountDetail, AccountManager, TokenRefreshWorker


XUID = "2535400000000000"


def claims(xuid=XUID, user_hash="user-hash"):
    return {"DisplayClaims": {"xui": [{"uhs": user_hash, "xid": xuid}]}}


def test_xuid_lookup_reuses_existing_claims(monkeypatch):
    request = Mock()
    monkeypatch.setattr(authentication, "get_xsts_token", request)
    assert authentication.get_xbox_xuid("xbox-token", "user-hash", claims()) == XUID
    request.assert_not_called()


def test_xuid_lookup_uses_separate_xbox_relying_party(monkeypatch):
    request = Mock(return_value=("xbox-service-token", claims()))
    monkeypatch.setattr(authentication, "get_xsts_token", request)
    assert authentication.get_xbox_xuid("xbox-token", "user-hash", {}) == XUID
    request.assert_called_once_with("xbox-token", relying_party="https://xboxlive.com")


def test_optional_xuid_lookup_failure_does_not_fail_login(monkeypatch):
    monkeypatch.setattr(authentication, "get_xsts_token", Mock(side_effect=AuthenticationException("unavailable")))
    assert authentication.get_xbox_xuid("xbox-token", "user-hash", {}) is None


@pytest.mark.parametrize("data", [{}, {"DisplayClaims": None}, claims(user_hash="other-user"),
                                   claims(xuid="not-a-number"), claims(xuid="9" * 30)])
def test_invalid_or_other_user_claims_are_not_used(data):
    assert authentication.extract_xuid(data, "user-hash") is None


@pytest.mark.parametrize("xuid", [None, XUID])
def test_account_xuid_round_trip_and_launch_mapping(xuid):
    now = datetime.datetime.now(datetime.timezone.utc)
    accounts = get_account_sample()
    create_account(Account("id", "player", "token", "refresh", now, now, xuid=xuid), accounts)
    restored = convert_account_data_to_object(accounts, "id")
    assert restored.xuid == xuid
    detail = AccountDetail(
        display_name="player", id="id", username="player", minecraft_uuid="uuid",
        minecraft_name="player", avatar="", account_type="msa", access_token="token",
        refresh_token="refresh", access_token_expires_at=now, refresh_token_expires_at=now,
        user_properties=[], xuid=restored.xuid,
    )
    manager = SimpleNamespace(get_current_account_id=lambda: "id", get_account=lambda _: detail,
                              settings_use_system_keyring=False)
    launch = AccountManager.get_launch_account(manager)
    maps = ArgumentMappings(auth_xuid=launch.xuid, natives_directory="natives", classpath="client.jar")
    command = generate_launch_command(maps, "Main", "java", {"game": ["--xuid", "${auth_xuid}"]})
    assert command[-1] == (xuid or "${auth_xuid}")
    if xuid is None:
        with pytest.raises(ArgumentValueError):
            generate_launch_command(maps, "Main", "java", {"game": ["${auth_xuid}"]}, strict_placeholders=True)


def test_old_account_without_xuid_still_loads():
    now = datetime.datetime.now(datetime.timezone.utc)
    accounts = get_account_sample()
    raw, _ = create_account(Account("id", "player", "token", "refresh", now, now), accounts)
    raw.pop("xuid")
    assert convert_account_data_to_object(accounts, "id").xuid is None


def test_refresh_retains_minecraft_token_audience_and_emits_xuid(monkeypatch):
    monkeypatch.setattr(account_module, "refresh_microsoft_token", lambda *_: ("microsoft", "refresh", {}))
    monkeypatch.setattr(account_module, "get_xbox_token_and_user_hash", lambda *_: ("xbox", "user-hash", {}))
    monkeypatch.setattr(account_module, "get_xsts_token", lambda *_: ("minecraft-xsts", claims()))
    monkeypatch.setattr(account_module, "get_xbox_xuid", lambda *_: XUID)
    minecraft_login = Mock(return_value=("minecraft-token", {}))
    monkeypatch.setattr(account_module, "get_minecraft_access_token", minecraft_login)
    result, errors = [], []
    worker = TokenRefreshWorker("id", "refresh", "client")
    worker.succeeded.connect(lambda account_id, data: result.append(data))
    worker.failed.connect(lambda *args: errors.append(args))
    worker.run()
    assert not errors
    assert result[0]["xuid"] == XUID
    minecraft_login.assert_called_once_with("user-hash", "minecraft-xsts")


def test_placeholder_replacement_defaults_to_tolerant_mode():
    assert replace_placeholders("${missing}/${unset}", {"unset": None}) == "${missing}/${unset}"
    with pytest.raises(ArgumentValueError):
        replace_placeholders("${missing}", {}, strict=True)
