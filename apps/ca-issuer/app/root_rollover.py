# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where a root renewal stands, as the files in the PKI directory show it (R-1021).

The transitions are in app.rotation (stage_root, abort_root, switch_root, finish_root),
beside rotate_intermediates, whose lock and file writes they share; this module only
reads, so the boot can tell the phase without the rotation code. R is the root before
the renewal, N the new one, X the cross certificate (N signed by R).

    none        root.crt, root.key.enc: R, or N after a finished renewal
    staged      + root-next.crt, root-next.key.enc: N waits, R still signs
    switched    root.crt, root.key.enc: N; root-retired.pem: R; root-cross.pem: X
                (not after --no-cross); root-switch.json: when and how the switch ran
    switching   a switch stopped part way: running it again with the same options ends it
    finishing   a finish stopped part way: running it again ends it

The switch writes root-switch.json first and removes root-next.* last; the finish removes
root-switch.json last. Files no transition leaves are a RolloverError.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509

from app import pki

NEXT_CRT = "root-next.crt"
NEXT_KEY = "root-next.key.enc"
RETIRED = "root-retired.pem"
CROSS = "root-cross.pem"
STATE = "root-switch.json"

ROTATE_ROOT = "docker compose run --rm --no-deps ca-issuer python -m app.cli rotate-root"


class RolloverError(Exception):
    """The PKI directory holds files of a root renewal that no transition leaves behind;
    the message says which and what to do."""


@dataclass(frozen=True)
class Switch:
    """The record of a switch in root-switch.json."""

    switched_at: datetime.datetime
    compromised: tuple[str, ...]  # scopes given to the switch, sorted
    cross: bool  # False after --no-cross: no X, clients that trust only R lose the server
    # R leaves `chain` before finish: a switch or a later rotation with --compromised
    # set it, because a client that trusts R also trusts the replaced intermediates.
    drop_retired_root: bool

    def to_json(self) -> bytes:
        record = {
            "switched_at": self.switched_at.isoformat(),
            "compromised": list(self.compromised),
            "cross": self.cross,
            "drop_retired_root": self.drop_retired_root,
        }
        return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()

    @classmethod
    def from_json(cls, data: bytes) -> Switch:
        """ValueError if `data` is not a record as to_json writes one."""
        try:
            record = json.loads(data)
            switched_at = datetime.datetime.fromisoformat(record["switched_at"])
            compromised = record["compromised"]
            cross, drop = record["cross"], record["drop_retired_root"]
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError(f"not a switch record: {exc}") from exc
        if (
            switched_at.tzinfo is None
            or not isinstance(compromised, list)
            or not all(scope in pki.SCOPES for scope in compromised)
            or not isinstance(cross, bool)
            or not isinstance(drop, bool)
        ):
            raise ValueError("not a switch record: a field has the wrong type or value")
        return cls(switched_at, tuple(sorted(compromised)), cross, drop)


@dataclass(frozen=True)
class State:
    phase: str  # none | staged | switching | switched | finishing
    next_root: x509.Certificate | None  # root-next.crt
    retired_root: x509.Certificate | None  # root-retired.pem
    cross: x509.Certificate | None  # root-cross.pem
    switch: Switch | None  # root-switch.json


def load_state(pki_dir: Path) -> State:
    """The phase of a root renewal in `pki_dir` and the certificates it holds. Only reads;
    checking the certificates against each other is up to the caller. A root-next.key.enc
    alone is a stage that stopped before its certificate: phase none, the next stage
    overwrites it and abort removes it."""
    present = {
        name for name in (NEXT_CRT, NEXT_KEY, RETIRED, CROSS, STATE) if (pki_dir / name).exists()
    }
    next_root = _cert(pki_dir, NEXT_CRT) if NEXT_CRT in present else None
    retired = _cert(pki_dir, RETIRED) if RETIRED in present else None
    cross = _cert(pki_dir, CROSS) if CROSS in present else None
    if STATE not in present:
        if present & {RETIRED, CROSS}:
            found = ", ".join(sorted(present & {RETIRED, CROSS}))
            raise RolloverError(
                f"{pki_dir} holds {found} without {STATE}; no switch or finish leaves that, "
                "restore the PKI volume from the backup of the last step"
            )
        if next_root is not None and NEXT_KEY not in present:
            raise RolloverError(
                f"{pki_dir / NEXT_CRT} has no key {NEXT_KEY} beside it; remove the next root "
                f"with: {ROTATE_ROOT} abort, then stage again"
            )
        phase = "staged" if next_root is not None else "none"
        return State(phase, next_root, None, None, None)

    try:
        switch = Switch.from_json((pki_dir / STATE).read_bytes())
    except (OSError, ValueError) as exc:
        raise RolloverError(f"cannot read {pki_dir / STATE}: {exc}") from exc
    if present & {NEXT_CRT, NEXT_KEY}:
        phase = "switching"
    elif retired is None and cross is not None:
        raise RolloverError(
            f"{pki_dir} holds {CROSS} without {RETIRED}; no switch or finish leaves that, "
            "restore the PKI volume from the backup of the last step"
        )
    elif not switch.cross and cross is not None:
        raise RolloverError(
            f"{pki_dir / CROSS} exists, but {STATE} records a switch without a cross "
            "certificate; restore the PKI volume from the backup of the last step"
        )
    elif retired is None or (switch.cross and cross is None):
        phase = "finishing"
    else:
        phase = "switched"
    return State(phase, next_root, retired, cross, switch)


def _cert(pki_dir: Path, name: str) -> x509.Certificate:
    try:
        return pki.cert_from_pem((pki_dir / name).read_bytes())
    except (OSError, ValueError) as exc:
        raise RolloverError(f"cannot read {pki_dir / name}: {exc}") from exc
