# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reads the proxy lists of the frps dashboard that the frps supervisor puts into
FRPS_STATE_DIR, one file a proxy type (proxy-<type>.json).

The server cannot reach the dashboard: frps sits in a network of its own. So the supervisor
fetches /api/proxy/<type> over loopback at every poll (5 s) while frps runs, and writes each
answer as frps gave it (apps/frps/frps-supervisor.sh, fetch_proxies). Neither the supervisor's
container nor frps is trusted here: the file is read strictly against the format below, any
deviation makes it invalid, and the reader never raises. The proxy type comes from the file
name, the age from its mtime, both the supervisor's.

Format, as frps 0.69.1 answers:

    {"proxies": [{"name": "<str>", "status": "<str>", "curConns": <int>, ...}, ...]}

- a regular file (no symlink) of at most 1 MiB, UTF-8 JSON without duplicate keys, NaN or
  Infinity
- an object with the list "proxies" of objects; of the keys the status view shows
  (PROXY_FIELDS) each one present has its type, a string without lone surrogates or an
  integer; other keys are left alone
- a file whose mtime is older than 60 s (STALE_AFTER of supervisor_status.py) is stale
"""

import json
import logging
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from app.modules.frp.supervisor_status import STALE_AFTER

logger = logging.getLogger(__name__)

MAX_BYTES = 1024 * 1024

# The keys of a proxy the status view shows (status_router.py), with their type.
PROXY_FIELDS: dict[str, type] = {
    "name": str,
    "status": str,
    "curConns": int,
    "clientVersion": str,
    "todayTrafficIn": int,
    "todayTrafficOut": int,
    "lastStartTime": str,
    "lastCloseTime": str,
}


class _Invalid(ValueError):
    pass


def read_proxy_list(
    state_dir: Path, proxy_type: str, *, now: datetime | None = None
) -> list[dict] | None:
    """The proxies of proxy-<proxy_type>.json in state_dir; None when the file is missing,
    stale or invalid. Never raises. now (aware UTC) defaults to the clock."""
    path = state_dir / f"proxy-{proxy_type}.json"
    try:
        raw, mtime = _read_bounded(path)
    except FileNotFoundError:
        return None
    except (OSError, _Invalid) as exc:
        logger.debug("frps proxy list %s unreadable: %s", path.name, exc)
        return None
    if (now or datetime.now(timezone.utc)) - mtime > STALE_AFTER:
        logger.debug("frps proxy list %s stale", path.name)
        return None
    try:
        doc = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_no_constant
        )
        return _proxies(doc)
    # ValueError covers _Invalid, JSONDecodeError, UnicodeDecodeError and an integer of
    # too many digits; RecursionError a deeply nested document.
    except (ValueError, RecursionError) as exc:
        logger.debug("frps proxy list %s invalid: %s", path.name, exc)
        return None


def _read_bounded(path: Path) -> tuple[bytes, datetime]:
    # The file comes from another container: a symlink would be resolved in this one, and
    # opening a FIFO without O_NONBLOCK would block until a writer shows up.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with open(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise _Invalid("not a regular file")
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise _Invalid(f"larger than {MAX_BYTES} bytes")
    return data, datetime.fromtimestamp(st.st_mtime, timezone.utc)


def _object(pairs: list[tuple[str, object]]) -> dict:
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise _Invalid("duplicate key")
    return obj


def _no_constant(name: str) -> None:
    raise _Invalid("NaN or Infinity")


def _proxies(doc: object) -> list[dict]:
    if not isinstance(doc, dict) or not isinstance(doc.get("proxies"), list):
        raise _Invalid("no list proxies")
    for proxy in doc["proxies"]:
        if not isinstance(proxy, dict):
            raise _Invalid("proxy not an object")
        for key, kind in PROXY_FIELDS.items():
            if key in proxy:
                _check(proxy[key], kind, key)
    return doc["proxies"]


def _check(value: object, kind: type, key: str):
    # type(), not isinstance(): true is no count.
    if type(value) is not kind:
        raise _Invalid(key)
    if kind is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            # A lone surrogate (\ud800) parses, but no JSON answer could carry it.
            raise _Invalid(key) from None
