# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Optional

from pydantic import field_validator

from app.core.bounds import RequestModel
from app.modules.frp.schemas import _reject_toml_breakers, _validate_tags


def _validate_server_name(v: Optional[str]) -> Optional[str]:
    """The server name becomes an FRP identifier in generated TOML (frpc
    `user`, visitor `serverUser`) and a path component in the bulk-ZIP
    (`clients/{name}/frpc.toml`) — reject TOML breakers and path separators/
    traversal at the boundary, same invariant as frp/schemas.py."""
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


class ServerCreate(RequestModel):
    name: str
    hostname: str
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
