# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Any, Literal, Optional

from pydantic import Field, ValidationError, field_validator, model_validator
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


class ConnectionCreate(RequestModel):
    name: str = Field(..., min_length=1, max_length=255)
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

    model_config = {"extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def _camel_case_only(cls, data: Any) -> Any:
        return _reject_snake_spellings(cls.__name__, data)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name darf nicht leer sein")
        return v.strip()


class ConnectionUpdate(RequestModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
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


class ImportRequest(RequestModel):
    connections: list[dict[str, Any]]
    mode: Literal["merge", "replace"]
