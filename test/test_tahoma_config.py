"""Unit tests for tahoma_config.py - the shared config/dispatch module used by
tahoma.py and get_devices_url.py. See CLAUDE.md for background.

These are network-free by design (no real gateway/cloud account needed) so
they can run in CI. Live device tests stay manual, per CLAUDE.md's testing
section.
"""

import argparse
import asyncio
import importlib

import pytest
from pyoverkiz.client import OverkizClient
from pyoverkiz.enums.server import APIType

import tahoma_config


def make_args(**overrides):
    defaults = dict(username=None, password=None, server=None, token=None,
                     pin=None, local=False, remote=False)
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# --- load_config -----------------------------------------------------------

def test_load_config_defaults_when_temp_missing(tmp_path):
    config = tahoma_config.load_config(str(tmp_path))
    assert config.token == ""
    assert config.gateway_id == ""
    assert config.local_remote == "remote"
    assert config.server == "somfy_europe"
    assert config.username == ""
    assert config.password == ""


def test_load_config_reads_temp_files(tmp_path):
    temp = tmp_path / "temp"
    temp.mkdir()
    (temp / "token.txt").write_text("mytoken\n")
    (temp / "gateway_id.txt").write_text("1234-5678-9012\n")
    (temp / "local_remote.txt").write_text("local\n")
    (temp / "server_choosen.txt").write_text("somfy_america\n")

    config = tahoma_config.load_config(str(tmp_path))
    assert config.token == "mytoken"
    assert config.gateway_id == "1234-5678-9012"
    assert config.local_remote == "local"
    assert config.server == "somfy_america"


# --- apply_cli_overrides -----------------------------------------------------

def test_apply_cli_overrides_username_password_server():
    config = tahoma_config.Config()
    tahoma_config.apply_cli_overrides(
        config, make_args(username="bob", password="secret", server="somfy_america")
    )
    assert config.username == "bob"
    assert config.password == "secret"
    assert config.server == "somfy_america"


def test_apply_cli_overrides_token_and_pin():
    config = tahoma_config.Config()
    tahoma_config.apply_cli_overrides(config, make_args(token="tok", pin="0001-0002-0003"))
    assert config.token == "tok"
    assert config.gateway_id == "0001-0002-0003"


def test_apply_cli_overrides_local_and_remote_flags():
    config = tahoma_config.Config(local_remote="remote")
    tahoma_config.apply_cli_overrides(config, make_args(local=True))
    assert config.local_remote == "local"

    tahoma_config.apply_cli_overrides(config, make_args(remote=True))
    assert config.local_remote == "remote"


def test_apply_cli_overrides_leaves_unset_fields_untouched():
    config = tahoma_config.Config(username="existing")
    tahoma_config.apply_cli_overrides(config, make_args())
    assert config.username == "existing"


# --- resolve_local_capability ------------------------------------------------

def test_resolve_local_capability_remote_configured_stays_remote():
    config = tahoma_config.Config(local_remote="remote")
    assert tahoma_config.resolve_local_capability(config) == "remote"


def test_resolve_local_capability_local_with_capable_category():
    config = tahoma_config.Config(local_remote="local")
    mode = tahoma_config.resolve_local_capability(
        config, category="pergola", action="stop",
        local_capable_categories={"pergola", "shutter"},
    )
    assert mode == "local"


def test_resolve_local_capability_local_with_incapable_category_falls_back(capsys):
    config = tahoma_config.Config(local_remote="local")
    mode = tahoma_config.resolve_local_capability(
        config, category="scene", action="run",
        local_capable_categories={"pergola", "shutter"},
    )
    assert mode == "remote"
    assert "not yet supported for local use" in capsys.readouterr().out


def test_resolve_local_capability_no_category_check_stays_local():
    config = tahoma_config.Config(local_remote="local")
    assert tahoma_config.resolve_local_capability(config) == "local"


# --- check_local_credentials -------------------------------------------------

def test_check_local_credentials_ok_when_both_present():
    config = tahoma_config.Config(token="tok", gateway_id="0001-0002-0003")
    ok, message = tahoma_config.check_local_credentials(config)
    assert ok is True
    assert message == ""


@pytest.mark.parametrize(
    "token,gateway_id,expected_substrings",
    [
        ("", "", ["token", "gateway_id"]),
        ("tok", "", ["gateway_id"]),
        ("", "0001-0002-0003", ["token"]),
    ],
)
def test_check_local_credentials_reports_whats_missing(token, gateway_id, expected_substrings):
    config = tahoma_config.Config(token=token, gateway_id=gateway_id)
    ok, message = tahoma_config.check_local_credentials(config)
    assert ok is False
    for substring in expected_substrings:
        assert substring in message


# --- build_client ------------------------------------------------------------
# This is the construction path that broke across the pyoverkiz 2.1.0
# migration (positional args -> keyword-only credentials=/server=,
# OverkizServer -> ServerConfig). Exercising it here is the main regression
# guard against the *next* pyoverkiz upgrade.

async def _build_and_inspect(mode, config, **kwargs):
    """OverkizClient() opens an aiohttp.ClientSession when none is passed,
    which requires a running event loop - hence the asyncio.run() wrapper
    around every build_client() call in these tests.
    """
    client = tahoma_config.build_client(mode, config, **kwargs)
    try:
        return type(client), client.server_config.api_type, client.server_config.endpoint
    finally:
        await client.close()


def test_build_client_local_mode():
    config = tahoma_config.Config(token="tok", gateway_id="1234-5678-9012")
    client_type, api_type, endpoint = asyncio.run(
        _build_and_inspect("local", config, verify_ssl=False)
    )
    assert client_type is OverkizClient
    assert api_type == APIType.LOCAL
    assert "1234-5678-9012" in endpoint


def test_build_client_remote_mode():
    config = tahoma_config.Config(username="bob", password="secret", server="somfy_europe")
    client_type, api_type, _ = asyncio.run(_build_and_inspect("remote", config))
    assert client_type is OverkizClient
    assert api_type == APIType.CLOUD


# --- import surface ------------------------------------------------------

@pytest.mark.parametrize("module_name", ["tahoma_config", "get_devices_url", "tahoma"])
def test_first_party_modules_import_cleanly(module_name):
    """Would have caught today's pyoverkiz 2.1.0 breakage: renamed
    OverkizServer/NotAuthenticatedException, removed Device.id/Gateway.id,
    Command becoming keyword-only, execute_command/get_scenarios/
    cancel_command being renamed - all of these surface as import- or
    module-level errors, not just runtime ones.
    """
    importlib.import_module(module_name)
