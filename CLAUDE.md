# tahoma

Python CLI (`tahoma.py`) for controlling Somfy TaHoma home-automation devices
(shutters, sunscreens, pergolas, plugs, lights, alarms, heaters, sensors,
scenes) via the Overkiz API — either the cloud (`tahomalink.com` and friends)
or the TaHoma gateway's local API.

## Repo layout

- `tahoma.py` — the CLI entry point. Argument parsing, per-category action
  dispatch (open/close/stop/my/NUMBER/on/off/arm/... depending on category),
  and the actual `OverkizClient` command execution.
- `get_devices_url.py` — device discovery, invoked by `tahoma.py --getlist`
  (`-g`). Logs into Overkiz, lists devices + scenarios, classifies each
  device into a category by its `widget` string, and writes the per-category
  files under `temp/`.
- `pyoverkiz/` — vendored Overkiz API client. Upstream:
  https://github.com/iMicknl/python-overkiz-api. Treat as third-party code;
  prefer not to hand-edit unless fixing something that also needs upstreaming.
- `temp/*.txt` — **all runtime state and secrets, gitignored.** Contains:
  - `identifier_file.txt` — obfuscated (not strongly encrypted) cloud
    username:password
  - `token.txt` — local API token
  - `gateway_id.txt` — gateway PIN
  - `local_remote.txt` — `local` or `remote`, which API mode to prefer
  - `server_choosen.txt` — which cloud server (`somfy_europe`, etc.)
  - `list_of_tahoma_devices.txt` + per-category files (`shutters.txt`,
    `pergolas.txt`, `plugs.txt`, ...) — the user's actual home layout/device
    names

  **Never commit these, never print their full contents into commits, PR
  descriptions, or logs.** `.gitignore` excludes `temp/*.txt`, `temp/*.log`,
  `temp/newrelic.ini`, `__pycache__/`, `*.pyc`.

## Local API vs cloud API

Configured via `tahoma -c` (interactive) or `--pin`/`--token`/`--local`/
`--remote` flags. When `temp/local_remote.txt == 'local'` and both
`gateway_id.txt` and `token.txt` are populated, both `get_devices_url.py`
(`--getlist`) and `tahoma.py`'s command dispatch try the local gateway first:

```
OverkizClient(username="", password="", token=<token>,
              verify_ssl=False,
              server=OverkizServer(
                  endpoint="https://gateway-<pin>.local:8443/enduser-mobile-web/1/enduserAPI/",
                  ...))
```

**Gotcha:** `verify_ssl=False` must be passed to the `OverkizClient`
constructor itself, not just to the `aiohttp.TCPConnector`. The gateway uses
a self-signed cert; `OverkizClient.__init__` builds its own strict SSL
context (pinned to Overkiz's public CA) whenever `verify_ssl` is left at its
default `True`, independent of whatever SSL settings the caller's session/
connector has. Passing only `TCPConnector(verify_ssl=False)` silently does
nothing here.

**Gotcha 2:** commands with zero parameters must be sent as
`Command(SomeOverkizCommand, [])`, not `Command(SomeOverkizCommand)` /
`parameters=None`. The local gateway API returns
`{'error': 'nil', 'errorCode': 'UNSPECIFIED_ERROR'}` for `parameters=None`
even on commands that take no arguments.

If local API login fails, both scripts fall back to the cloud API using the
stored/`-u`/`-p` username+password.

## Device categories are not 1:1 with hardware

Categories (`shutter`, `sunscreen`, `plug`, `light`, `alarm`, `heater`,
`pergola`, `scene`, `sensor`, `spotalarm`) are assigned in
`get_devices_url.py` by matching substrings in the Overkiz `widget` name.
Multiple, behaviorally different widgets can land in the same category —
e.g. `pergola` covers both:

- `BioclimaticPergola` — tilting slats, no `open`/`close`/`setClosure`
  commands; uses `openSlats`/`closeSlats`/`setOrientation` instead.
- `PergolaHorizontalAwning` / `PositionableTiltedScreen` — behaves like a
  sunscreen/shutter: `open`/`close`/`setClosure`.

`tahoma.py`'s pergola action block branches on the matched device's widget
(stored as the 3rd CSV column in `temp/pergolas.txt`) to pick the right
command set. **Any category-wide behavior change must check the widget of
the specific device(s) involved** rather than assuming every device sharing
a category behaves the same — a category-wide change that isn't
widget-scoped can silently break other users' hardware even though it fixes
one case.

## Testing changes

There's no meaningful automated test suite (`test/test.py` is empty).
Practical workflow, cheapest/safest first:

1. **Syntax check** — cheap sanity check before anything else:
   ```
   python -c "import ast; ast.parse(open('tahoma.py',encoding='utf-8').read())"
   python -c "import ast; ast.parse(open('get_devices_url.py',encoding='utf-8').read())"
   ```

2. **Dry-test command selection logic in isolation** — no network calls, safe
   any time. Copy just the branching logic you changed into a standalone
   snippet, feed it every relevant widget string / action, and print what
   `Command(...)` + params would result, e.g.:
   ```python
   from pyoverkiz.models import Command
   from pyoverkiz.enums import OverkizCommand
   # ...replicate the branch, call it for each widget type you care about...
   ```
   This catches logic mistakes (wrong command chosen for a widget) and
   protocol mistakes (e.g. the `parameters=None` vs `[]` gotcha above) before
   they reach a real device.

3. **Regression-check against the last known-good commit:**
   ```
   git diff <last-good-commit> -- tahoma.py get_devices_url.py
   ```
   For every changed branch, confirm the non-target-widget / "else" path is
   byte-for-byte the same command+params as before. This matters because of
   the shared-category-different-hardware issue above.

4. **Read-only live checks** — safe against a real gateway, don't move
   anything:
   - `python tahoma.py --getlist` (rewrites `temp/*.txt` device lists)
   - `python tahoma.py --list`
   - `python tahoma.py -ln` / `-lnf` (list device names by category)
   - `python tahoma.py -la` / `-laf` (list actions by category)

5. **Live device commands** — physically move/trigger real hardware. Only
   do this with explicit user go-ahead, one action at a time. Prefer a
   no-op-ish action first when validating a new code path end to end (`stop`
   or `my` before `open`/`close`), then confirm destructive actions once the
   harmless one round-trips cleanly.
