#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""lock-pins.py — is every pin of a lock installed exactly as the lock names it?

    python3 scripts/dev/lock-pins.py <requirements.txt> [--freeze <file>]

Reads the ``name==version`` lines of a pip-compile lock and compares them with
the running environment (``importlib.metadata``), or with a ``pip freeze``
listing given as ``--freeze``. The images install the lock with
``--require-hashes``; the tests install the loose ``requirements.in`` on top of
it, and pip upgrades a locked package without a word whenever a dev dependency
asks for more. This check is what makes that visible: green only if the suite
really ran against the versions the image ships.

Extras are dropped (``uvicorn[standard]==x`` is ``uvicorn``), names are
compared in their PEP 503 form, hash and comment lines are skipped. Any other
line — an environment marker, an ``-e``, an option, a ``>=`` — is refused
rather than skipped: a pin this check cannot read is a pin it would silently
never compare. Versions are compared as written (case aside); the lock and the
installed metadata both come from the same wheel.

Exit codes: 0 every pin installed as locked · 1 a pin is missing or installed
in another version (each one is named) · 2 the lock is empty, unreadable or has
a line this check does not understand — never green.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import re
import sys
from pathlib import Path

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)\s*\\?\s*$")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_lock(text: str) -> dict[str, str]:
    """Pins of a pip-compile lock; ValueError on a line that is not one."""
    pins: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("--hash"):
            continue
        m = _PIN.match(line)
        if not m:
            raise ValueError(f"line {n} is not a pin this check understands: {line}")
        pins[_norm(m.group(1))] = m.group(2)
    return pins


def read_freeze(text: str) -> dict[str, str]:
    """``name==version`` lines of a pip freeze; URL and editable installs have no version to compare."""
    installed: dict[str, str] = {}
    for raw in text.splitlines():
        m = _PIN.match(raw.strip())
        if m:
            installed.setdefault(_norm(m.group(1)), m.group(2))
    return installed


def read_environment() -> dict[str, str]:
    installed: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            # The first one wins, as it does for import: a shadowed copy further
            # down sys.path is not what the suite ran against.
            installed.setdefault(_norm(name), dist.version)
    return installed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="compare a pip-compile lock with the installed packages"
    )
    parser.add_argument("lock", type=Path, help="the pip-compile lock (requirements.txt)")
    parser.add_argument(
        "--freeze", type=Path, help="a pip freeze listing instead of the running environment"
    )
    args = parser.parse_args(argv)

    try:
        pins = read_lock(args.lock.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"lock-pins: {args.lock}: {exc}", file=sys.stderr)
        return 2
    if not pins:
        print(f"lock-pins: {args.lock}: no pins — an empty lock proves nothing", file=sys.stderr)
        return 2
    if args.freeze:
        try:
            installed = read_freeze(args.freeze.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            print(f"lock-pins: {args.freeze}: {exc}", file=sys.stderr)
            return 2
    else:
        installed = read_environment()

    drift = 0
    for name, locked in sorted(pins.items()):
        have = installed.get(name)
        if have is None:
            print(f"  missing  {name}: locked {locked}, not installed")
            drift += 1
        elif have.lower() != locked.lower():
            print(f"  drift    {name}: locked {locked}, installed {have}")
            drift += 1
    if drift:
        print(f"lock-pins: {drift} of {len(pins)} pins differ from {args.lock}")
        return 1
    print(f"lock-pins: {len(pins)} pins installed as locked ({args.lock})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
