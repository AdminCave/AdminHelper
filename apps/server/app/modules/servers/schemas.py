# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Optional

from pydantic import BaseModel, field_validator

from app.core.bounds import RequestModel
from app.modules.connections.schemas import ConnectionOut
from app.modules.frp.schemas import FrpTunnelOut, _reject_toml_breakers, _validate_tags


def _validate_server_name(v: Optional[str]) -> Optional[str]:
    """The server name is a path component in the bulk-ZIP
    (`clients/{name}/frpc.toml`; frpc and the visitor know the server by its ID) —
    reject TOML breakers and path separators/traversal at the boundary, same
    invariant as frp/schemas.py."""
    if v is None:
        return v
    v = v.strip()
    if not v:
        raise ValueError("darf nicht leer sein")
    if len(v) > 100:
        raise ValueError("darf höchstens 100 Zeichen lang sein")
    _reject_toml_breakers(v)
    if "/" in v or v in {".", ".."}:
        raise ValueError("darf keine Pfad-Zeichen (/, '.', '..') enthalten")
    return v


# Windows device names (Microsoft Learn, "Naming Files, Paths, and Namespaces"): reserved
# in every directory, case-insensitive, with any extension too ("NUL.txt" is NUL), and
# Windows counts the superscripts 1-3 as digits of COM#/LPT#. CONIN$ and CONOUT$ are not
# on that page; Python's ntpath.isreserved lists them, so they are refused too (R-1176).
_WINDOWS_DEVICE_NAMES = frozenset(
    ["con", "prn", "aux", "nul", "conin$", "conout$"]
    + [f"{dev}{d}" for dev in ("com", "lpt") for d in "123456789\u00b9\u00b2\u00b3"]
)


def reject_windows_unsafe_server_name(v: str) -> None:
    """A new or renamed server name must also be a folder name on Windows: the bulk-ZIP
    puts it into clients/<name>/frpc.toml. Not in the schema, because names stored before
    stay valid and an edit that sends one back unchanged must pass (R-1056)."""
    if ":" in v:
        raise ValueError("must not contain ':'")
    if v.split(".", 1)[0].rstrip(" ").lower() in _WINDOWS_DEVICE_NAMES:
        raise ValueError(
            "must not be a reserved Windows device name (CON, PRN, AUX, NUL, CONIN$, CONOUT$, COM1-9, LPT1-9)"
        )


def stored_hostname(name: str, hostname: Optional[str]) -> Optional[str]:
    """The hostname to store: None when the address follows the name (R-1210) — none given,
    blank, or the name itself (case and outer whitespace aside, as an older client sends the
    address it was shown); else the address without outer whitespace."""
    if hostname is None or not hostname.strip():
        return None
    hostname = hostname.strip()
    return None if hostname.lower() == name.strip().lower() else hostname


class ServerCreate(RequestModel):
    name: str
    # None or blank: the address follows the name.
    hostname: Optional[str] = None
    os_type: Optional[str] = None
    tags: list[str] = []
    notes: Optional[str] = ""

    _clean_name = field_validator("name")(_validate_server_name)
    _clean_tags = field_validator("tags", mode="before")(_validate_tags)


class ServerUpdate(RequestModel):
    name: Optional[str] = None
    hostname: Optional[str] = None
    os_type: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None

    _clean_name = field_validator("name")(_validate_server_name)
    _clean_tags = field_validator("tags", mode="before")(_validate_tags)


class ServerSummary(BaseModel):
    """One server as GET /api/servers/summary lists it."""

    id: str
    name: str
    hostname: str


class ServerOut(BaseModel):
    id: str
    name: str
    # The address the server is reached at: the own hostname, else the name.
    hostname: str
    # True when an own hostname is stored, False when the address follows the name.
    customHostname: bool
    osType: Optional[str]
    tags: list[str]
    notes: str
    createdAt: Optional[str]
    connections: list[ConnectionOut]
    frpTunnels: list[FrpTunnelOut]


class InternalServerOut(BaseModel):
    """One server as the monitoring service's tag-sync reads it."""

    id: str
    hostname: str
    name: str
    tags: list[str]
