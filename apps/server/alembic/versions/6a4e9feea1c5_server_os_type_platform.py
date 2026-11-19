# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""server_os_type_platform: servers.os_type becomes a platform value

Revision ID: 6a4e9feea1c5
Revises: d7b2e4c6a8f0
Create Date: 2026-11-19

os_type was free text; the API now takes only linux, windows, freebsd, opnsense, other or
NULL (R-1594). The upgrade maps every stored text: a Linux distribution name -> linux,
win... -> windows, freebsd, opnsense, anything else -> other; empty or blank -> NULL. The
downgrade leaves the platform values in place: the free text is gone.
"""

import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6a4e9feea1c5"
down_revision: Union[str, Sequence[str], None] = "d7b2e4c6a8f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Matched against the first word of the text (letters only), so "Archive box" or
# "Debianish" do not count; distributions whose name carries "linux" match on that.
_LINUX = {
    "ubuntu",
    "debian",
    "centos",
    "rhel",
    "redhat",
    "red",
    "fedora",
    "rocky",
    "alma",
    "almalinux",
    "suse",
    "opensuse",
    "sles",
    "arch",
    "alpine",
    "mint",
    "raspbian",
    "gentoo",
    "proxmox",
    "pve",
    "kali",
    "manjaro",
    "linuxmuster",
}


def platform_of(text: str | None) -> str | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    first = re.match(r"[a-z]*", t).group()
    # OPNsense before FreeBSD: an OPNsense text may name the FreeBSD it runs on.
    if "opnsense" in t:
        return "opnsense"
    if "freebsd" in t:
        return "freebsd"
    # "linux" before the Windows test: "Wind River Linux" is a Linux.
    if "linux" in t:
        return "linux"
    if "windows" in t or first.startswith("win"):
        return "windows"
    if first in _LINUX and not (first == "red" and not t.startswith("red hat")):
        return "linux"
    return "other"


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT DISTINCT os_type FROM servers WHERE os_type IS NOT NULL")
    ).all()
    for (old,) in rows:
        new = platform_of(old)
        if new != old:
            conn.execute(
                sa.text("UPDATE servers SET os_type = :new WHERE os_type = :old"),
                {"new": new, "old": old},
            )


def downgrade() -> None:
    """Leave the platform values in place on purpose.

    The free text the upgrade mapped is not kept anywhere, so it cannot come back; and the
    platform values are valid free text for the older schema, which took any string.
    """
