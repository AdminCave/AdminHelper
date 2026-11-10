# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from typing import Annotated, Any, Literal, Optional

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails

from app.core.bounds import RequestModel
from app.modules.connections.models import _CAMEL_TO_SNAKE

# Only the camelCase spelling of a mapped field is accepted. Connection.from_dict/
# update_from_dict map the API names to columns and keep any other key as an extra
# entry, so a snake_case spelling would not set the field it names; the 422 says so,
# and the column stays set only through its API name and the checks on it (serverId
# against a key's server binding, the known server). extra=allow stays for the rest.
_SNAKE_SPELLINGS = {snake: camel for camel, snake in _CAMEL_TO_SNAKE.items()}


def _reject_snake_spellings(model: str, data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    found = sorted(key for key in data if key in _SNAKE_SPELLINGS)
    if not found:
        return data
    raise ValidationError.from_exception_data(
        model,
        [
            InitErrorDetails(
                type="value_error",
                loc=(key,),
                input=data[key],
                ctx={"error": ValueError(f"unknown field, use {_SNAKE_SPELLINGS[key]}")},
            )
            for key in found
        ],
    )


# Per-connection options (R-1066). The desktop turns these into command-line arguments for
# ssh and FreeRDP, so every free-form value is held to a strict format here, the first of two
# boundaries (the desktop checks again): host names, ports 1-65535, no leading "-" (it would
# read as a flag), no whitespace or control characters. Unknown keys are refused, and a field
# left out means "the global default".
_NAMED_HOST = r"[A-Za-z0-9_](?:[A-Za-z0-9._-]{0,252})"
_HOST = rf"(?:\[[0-9A-Fa-f:.]+\]|{_NAMED_HOST})"
_PORT = r"(?:6553[0-5]|655[0-2][0-9]|65[0-4][0-9]{2}|6[0-4][0-9]{3}|[1-5][0-9]{4}|[1-9][0-9]{0,3})"
_USER = r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}"
_JUMP_HOP = rf"(?:{_USER}@)?{_HOST}(?::{_PORT})?"
# An IPv6 literal only in the last hop (R-1158): ssh unwraps the last hop itself, but copies
# the hops before it unchanged into a ProxyCommand that does not keep the brackets as written.
_EARLIER_HOP = rf"(?:{_USER}@)?{_NAMED_HOST}(?::{_PORT})?"
_JUMP_RE = re.compile(rf"(?:{_EARLIER_HOP},){{0,7}}{_JUMP_HOP}")
_LISTEN_RE = re.compile(rf"(?:(?:\*|{_HOST}):)?{_PORT}")
_TARGET_RE = re.compile(rf"{_HOST}:{_PORT}")
_GATEWAY_RE = re.compile(rf"{_HOST}(?::{_PORT})?")
_SIZE_RE = re.compile(r"([0-9]{3,4})[xX]([0-9]{3,4})")


def _matching(pattern: re.Pattern, what: str):
    def check(value: str) -> str:
        if not pattern.fullmatch(value):
            raise ValueError(f"invalid {what}")
        return value

    return AfterValidator(check)


def _screen_size(value: str) -> str:
    m = _SIZE_RE.fullmatch(value)
    # The range the desktop's parse_custom_size accepts.
    if not m or not (640 <= int(m[1]) <= 7680 and 480 <= int(m[2]) <= 4320):
        raise ValueError("invalid size, use WxH between 640x480 and 7680x4320")
    return value


class _Options(RequestModel):
    model_config = ConfigDict(extra="forbid")


class SshForward(_Options):
    """One port forward: L and R need a target host:port, D (SOCKS) takes none."""

    type: Literal["L", "R", "D"]
    listen: Annotated[str, Field(max_length=300), _matching(_LISTEN_RE, "listen address")]
    target: Optional[
        Annotated[str, Field(max_length=300), _matching(_TARGET_RE, "target host:port")]
    ] = None

    @model_validator(mode="after")
    def _target_matches_type(self) -> "SshForward":
        if self.type == "D" and self.target is not None:
            raise ValueError("a dynamic forward (D) takes no target")
        if self.type != "D" and self.target is None:
            raise ValueError(f"a {self.type} forward needs a target")
        return self


class SshOptions(_Options):
    jumpHost: Optional[Annotated[str, Field(max_length=1000), _matching(_JUMP_RE, "jump host")]] = (
        None
    )
    forwards: Optional[list[SshForward]] = Field(None, max_length=32)
    agentForwarding: Optional[bool] = None
    compression: Optional[bool] = None
    # Seconds, for ServerAliveInterval.
    keepalive: Optional[int] = Field(None, ge=1, le=3600)
    authMethod: Optional[Literal["key", "agent", "password"]] = None


class RdpOptions(_Options):
    scalingMode: Optional[Literal["auto", "normal", "hdpi"]] = None
    windowMode: Optional[Literal["fit", "fullscreen", "multimon", "custom"]] = None
    customSize: Optional[Annotated[str, AfterValidator(_screen_size)]] = None
    performanceProfile: Optional[Literal["auto", "lan", "broadband", "low"]] = None
    drives: Optional[bool] = None
    audio: Optional[Literal["local", "remote", "off"]] = None
    printers: Optional[bool] = None
    gateway: Optional[
        Annotated[str, Field(max_length=300), _matching(_GATEWAY_RE, "gateway host[:port]")]
    ] = None
    nla: Optional[bool] = None


class ConnectionOptions(_Options):
    ssh: Optional[SshOptions] = None
    rdp: Optional[RdpOptions] = None


class ConnectionCreate(RequestModel):
    # With a server both are optional: the display name derives from the server's name
    # (R-1210), `label` is the own text in it; `name` is what a client from before sends.
    # Without a server one of them is the name and must not be blank.
    name: Optional[str] = Field(None, max_length=255)
    label: Optional[str] = Field(None, max_length=255)
    # The desktop/web clients only render ssh/rdp/web; reject anything else at
    # the boundary instead of persisting a kind no consumer can handle.
    kind: Literal["ssh", "rdp", "web"]
    host: Optional[str] = ""
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = ""
    domain: Optional[str] = ""
    keyPath: Optional[str] = ""
    url: Optional[str] = ""
    notes: Optional[str] = ""
    tags: Optional[list[str]] = []
    trustCert: Optional[bool] = False
    lastUsed: Optional[str] = None
    serverId: Optional[str] = None
    options: Optional[ConnectionOptions] = None

    model_config = {"extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def _camel_case_only(cls, data: Any) -> Any:
        return _reject_snake_spellings(cls.__name__, data)

    @field_validator("name", "label")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v

    @model_validator(mode="after")
    def name_not_blank_without_server(self) -> "ConnectionCreate":
        own = self.label if self.label is not None else self.name
        if self.serverId is None and not (own or "").strip():
            raise ValueError("Name darf nicht leer sein")
        return self


class ConnectionUpdate(RequestModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    # The own text of the display name of a connection with a server; '' takes it away.
    label: Optional[str] = Field(None, max_length=255)
    # Same gate as ConnectionCreate: no client renders anything but ssh/rdp/web,
    # so reject others here too — otherwise PUT could persist a kind that Create
    # rejects and no consumer (launcher, hub) can handle.
    kind: Optional[Literal["ssh", "rdp", "web"]] = None
    host: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = None
    domain: Optional[str] = None
    keyPath: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    trustCert: Optional[bool] = None
    lastUsed: Optional[str] = None
    serverId: Optional[str] = None
    options: Optional[ConnectionOptions] = None

    model_config = {"extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def _camel_case_only(cls, data: Any) -> Any:
        return _reject_snake_spellings(cls.__name__, data)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("Name darf nicht leer sein")
        return v.strip() if v else v


class TouchRequest(RequestModel):
    # The client's hostname, the device of the session. No control characters: it is shown
    # as text in the history.
    device: Optional[str] = Field(
        None, min_length=1, max_length=255, pattern=r"^[^\x00-\x1f\x7f]+$"
    )


class ImportRequest(RequestModel):
    connections: list[dict[str, Any]]
    mode: Literal["merge", "replace"]


# Responses


class ConnectionOut(BaseModel):
    """Connection.to_dict. The extra fields a client stored ride along as further keys."""

    model_config = ConfigDict(extra="allow")

    id: str
    # The display name (R-1210): "{server} · {label}" or "{server} · SSH|RDP|Web" (" (FRP)" over
    # a tunnel) for a connection with a server, else its name.
    name: str
    # The stored own text of the display name; without a server the name itself.
    label: str
    # Not a Literal: the column takes any string, and rows from before the import validation
    # (v0.36.0) can hold another kind.
    kind: str
    host: str
    port: Optional[int]
    username: str
    domain: str
    keyPath: str
    url: str
    notes: str
    # Any, not a list: an import before v0.36.0 stored a non-list value as it came, and such a row
    # must not turn the whole list into a 500.
    tags: Any
    trustCert: bool
    lastUsed: Optional[str]
    # Only set when the connection belongs to a server; the routes leave it out otherwise.
    serverId: Optional[str] = None
    # Only set when the connection has options of its own (ConnectionOptions). A dict, not the
    # model: a row must not turn the whole list into a 500 should the schema ever get stricter.
    options: Optional[dict[str, Any]] = None


class ConnectionTouchOut(ConnectionOut):
    # The session the touch opened; the client ends it with .../sessions/{sessionId}/end.
    sessionId: str


class ConnectionSessionOut(BaseModel):
    id: str
    device: Optional[str]
    startedAt: str
    endedAt: Optional[str]


class ConnectionImportResult(BaseModel):
    imported: int
    mode: str
