"""Shared config loading, CLI-override, and local/remote API-mode resolution
for tahoma.py and get_devices_url.py. See CLAUDE.md for the local-vs-cloud
API background and the two OverkizClient gotchas (verify_ssl constructor arg,
parameters=[] for zero-arg commands).
"""

import base64
import os
from dataclasses import dataclass
from hashlib import sha256

from pyoverkiz.auth.credentials import LocalTokenCredentials, UsernamePasswordCredentials
from pyoverkiz.client import OverkizClient
from pyoverkiz.const import LOCAL_API_PATH, SUPPORTED_SERVERS
from pyoverkiz.enums.server import APIType
from pyoverkiz.models import ServerConfig


@dataclass
class Config:
    username: str = ""
    password: str = ""
    server: str = "somfy_europe"
    token: str = ""
    gateway_id: str = ""
    local_remote: str = "remote"


def _read_file(path, default=""):
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return default


def load_config(base_dir):
    """Load persisted config from temp/*.txt. Written only by `tahoma -c`."""
    temp = os.path.join(base_dir, 'temp')
    config = Config()
    config.token = _read_file(os.path.join(temp, 'token.txt'))
    config.gateway_id = _read_file(os.path.join(temp, 'gateway_id.txt'))
    config.local_remote = _read_file(os.path.join(temp, 'local_remote.txt'), "remote")
    config.server = _read_file(os.path.join(temp, 'server_choosen.txt'), "somfy_europe")

    init_file = os.path.join(base_dir, '__init__.py')
    try:
        with open(init_file, 'r'):
            pass
        init_str = sha256(b"init").hexdigest()
    except FileNotFoundError:
        init_str = "None"

    passwd_file = os.path.join(temp, 'identifier_file.txt')
    try:
        with open(passwd_file, 'rb') as f:
            content_str = base64.b64decode(f.read()).decode('utf-8')
        parts = content_str.split(':')
        if len(parts[0]) > 0:
            config.username = parts[0]
        if len(parts) > 1 and len(parts[1]) > 0:
            config.password = parts[1].replace(init_str, "")
    except FileNotFoundError:
        pass

    return config


def apply_cli_overrides(config, args):
    """Apply --username/--password/--server/--token/--pin/--local/--remote
    on top of the loaded config, in-memory only (never rewrites temp/*.txt).
    """
    if getattr(args, 'username', None):
        config.username = args.username
        print("Your USERNAME has been taken into account")
    if getattr(args, 'password', None):
        config.password = args.password
        print("Your PASSWORD has been taken into account")
    if getattr(args, 'server', None):
        config.server = args.server
        print("The server: " + config.server + " has been taken into account")
    if getattr(args, 'token', None):
        config.token = args.token
        print("Your token: " + config.token + " has been taken into account")
    if getattr(args, 'pin', None):
        config.gateway_id = args.pin
        print("Your gateway pin code: " + config.gateway_id + " has been taken into account")
    if getattr(args, 'local', False):
        config.local_remote = "local"
        print("Will use tahoma with the 'local' config")
    if getattr(args, 'remote', False):
        config.local_remote = "remote"
        print("Will use tahoma with the 'remote' config")
    return config


def resolve_local_capability(config, category=None, action=None, local_capable_categories=None):
    """Decide 'local' vs 'remote' based purely on config.local_remote and
    whether `category` is supported locally. Does NOT check whether
    token/gateway_id are actually present - see check_local_credentials for
    that, kept separate so callers can still attempt auto-provisioning
    (tahoma.py's get_token_or_gateway_id flow) instead of a hard fallback.
    Always prints why, when downgrading from local to remote. Returns mode.
    """
    if config.local_remote != 'local':
        return 'remote'

    if local_capable_categories is not None and category is not None \
            and category not in local_capable_categories:
        if action not in ('wait', 'attendre'):
            if action not in ('cancel', 'annuler'):
                print("Tahoma has been executed with the 'global' config because the '"
                      + category.lower() + "' category is not yet supported for local use")
            else:
                print("\nCan't perform a CANCEL action when using a local API of tahoma: "
                      "\nRun tahoma with the '--remote' argument.\n")
        return 'remote'

    return 'local'


def check_local_credentials(config):
    """Explicit check for whether local mode actually has what it needs.
    Returns (ok, message). message is set whenever ok is False, so callers
    can always surface *why* local isn't usable instead of failing silently.
    """
    missing = []
    if not config.token:
        missing.append('token')
    if not config.gateway_id:
        missing.append('gateway_id (pin)')
    if missing:
        return False, (
            "Local API selected but " + " and ".join(missing) + " not configured. "
            "Run 'tahoma -c' or pass --token/--pin. "
        )
    return True, ""


def build_client(mode, config, session=None, verify_ssl=False):
    """Construct a real OverkizClient directly - no eval()."""
    if mode == 'local':
        return OverkizClient(
            credentials=LocalTokenCredentials(token=config.token),
            verify_ssl=verify_ssl,
            session=session,
            server=ServerConfig(
                name="Somfy TaHoma (local)",
                endpoint=f"https://gateway-{config.gateway_id}.local:8443{LOCAL_API_PATH}",
                manufacturer="Somfy",
                api_type=APIType.LOCAL,
                configuration_url=None,
            ),
        )
    return OverkizClient(
        credentials=UsernamePasswordCredentials(username=config.username, password=config.password),
        server=SUPPORTED_SERVERS[config.server],
    )
