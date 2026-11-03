# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A PKI directory in one phase of a root renewal (R-1021), built with the real
transitions, for the tests of what the server material holds in each phase."""

import datetime
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509

from app import pki, root_rollover, rotation, storage
from app.storage import Intermediate

PW = b"pw"
NEXT_PW = b"next-pw"

# none and staged: before the switch; switched: with X; no-cross: switched without X;
# compromised: switched with --compromised for one scope; expired: switched, then R ran
# out; finished: after finish.
PHASES = ("none", "staged", "switched", "no-cross", "compromised", "expired", "finished")


@dataclass(frozen=True)
class Renewal:
    before: dict[str, Intermediate]  # ensure_hierarchy before the stage
    after: dict[str, Intermediate]  # ensure_hierarchy in the phase
    old_root: x509.Certificate  # R
    new_root: x509.Certificate | None  # N, None in phase none
    cross: x509.Certificate | None  # X as the switch wrote it


def renewed(monkeypatch, pki_dir: Path, phase: str, compromised: str = "access") -> Renewal:
    """Boot `pki_dir`, take it to `phase` and boot again. For expired the first boot
    lies ten days before R ends and the clock stays eleven days later afterwards."""
    if phase == "expired":
        then = pki._now() - datetime.timedelta(days=pki.VALIDITY_DAYS_ROOT - 10)
        with monkeypatch.context() as m:
            m.setattr(pki, "_now", lambda: then)
            before = storage.ensure_hierarchy(pki_dir, PW)
    else:
        before = storage.ensure_hierarchy(pki_dir, PW)
    old_root = pki.cert_from_pem((pki_dir / "root.crt").read_bytes())
    new_root = cross = None
    if phase != "none":
        new_root = rotation.stage_root(pki_dir, NEXT_PW)
    if phase not in ("none", "staged"):
        rotation.switch_root(
            pki_dir,
            NEXT_PW,
            None if phase == "no-cross" else PW,
            compromised=frozenset({compromised}) if phase == "compromised" else frozenset(),
            cross=phase != "no-cross",
        )
        if (pki_dir / root_rollover.CROSS).exists():
            cross = pki.cert_from_pem((pki_dir / root_rollover.CROSS).read_bytes())
    if phase == "finished":
        rotation.finish_root(pki_dir)
    if phase == "expired":
        later = pki._now() + datetime.timedelta(days=11)
        monkeypatch.setattr(pki, "_now", lambda: later)
    after = storage.ensure_hierarchy(pki_dir, None)
    return Renewal(before, after, old_root, new_root, cross)
