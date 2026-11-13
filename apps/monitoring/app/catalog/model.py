# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The shape of a catalog module: what it detects, what one instance is, which checks
it brings and which numbers its card shows.

A module is data, checked here when the catalog loads. The bounds are product rules,
not taste: a probe runs at most every 5 min, a test endpoint (one that makes the
service do real work) at most every 15 min (Kevin 2026-11-09), and a port in a module
is only a hint; the agent asks the port the process really listens on.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from app.catalog.sensors import (
    APP_VIEW_TARGETS,
    FIELD_PATTERN,
    SENSOR_TARGETS,
    SENSORS,
    field_allowed,
    validate_params,
)

INTERVALS = (300, 900, 3600, 86400)
TEST_OBJECT_MIN_INTERVAL = 900
MAX_FIELDS = 32

_SLUG = r"^[a-z0-9][a-z0-9_-]{0,63}$"
_KEY = r"^[a-z0-9][a-z0-9_]{0,63}$"
_NAME_ITEM = Annotated[str, Field(min_length=1, max_length=255)]
_ABS_PATH = Annotated[str, Field(pattern=r"^/[^\x00]*$", max_length=1024)]
_PACKAGE = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9+._-]{0,127}$")]
_PORT = Annotated[int, Field(ge=1, le=65535, strict=True)]
# A glob over an image tag (fnmatch: * and ?); Docker allows [A-Za-z0-9_.-] in a tag.
_TAG_GLOB = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.*?-]{1,128}$")]
_Scalar = StrictBool | StrictInt | StrictFloat | StrictStr


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class Marker(_Model):
    """A file or package whose presence tells the module is installed."""

    # Global in the plan, so it starts with the module id (checked on Module).
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,127}$")
    paths: list[_ABS_PATH] = Field(default_factory=list, max_length=16)
    packages: list[_PACKAGE] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def _not_empty(self) -> Marker:
        if not self.paths and not self.packages:
            raise ValueError("a marker needs paths or packages")
        return self


class Detect(_Model):
    container_images: list[_NAME_ITEM] = Field(default_factory=list, max_length=32)
    units: list[_NAME_ITEM] = Field(default_factory=list, max_length=32)
    processes: list[_NAME_ITEM] = Field(default_factory=list, max_length=32)
    markers: list[Marker] = Field(default_factory=list, max_length=16)
    # Hints only: a port is never assumed, the agent asks the one really listening.
    port_hints: list[_PORT] = Field(default_factory=list, max_length=16)

    def is_empty(self) -> bool:
        return not (self.container_images or self.units or self.processes or self.markers)


class Alternative(_Model):
    port_hint: _PORT
    scheme: Literal["http", "https", "tcp"]


class Target(_Model):
    kind: Literal["loopback", "container", "process", "unit", "port"]
    # Compose service of the instance's project whose container the check asks.
    service: str = Field("", max_length=255)
    # Without the service: the one container of the instance with the module's image that
    # no other check's service names (Nextcloud started by `docker run` or as `nextcloud`).
    image_fallback: StrictBool = False
    port_hint: _PORT | None = None
    scheme: Literal["http", "https", "tcp"] | None = None
    # In order: the first whose port the last scan saw at the container (Bitwarden's nginx
    # listens on 8443 with TLS and redirects 8080 there, on 8080 alone without).
    alternatives: list[Alternative] | None = Field(None, min_length=1, max_length=4)

    @model_validator(mode="after")
    def _consistent(self) -> Target:
        if self.image_fallback and not self.service:
            raise ValueError("image_fallback needs a service")
        if self.alternatives is not None:
            if self.kind != "container":
                raise ValueError("alternatives need a container target")
            if self.port_hint is not None or self.scheme is not None:
                raise ValueError("alternatives replace port_hint and scheme")
        return self


class Rule(_Model):
    field: str
    op: Literal["eq", "ne", "lt", "le", "gt", "ge", "in", "max_age", "delta_gt"]
    value: _Scalar | list[_Scalar]
    level: Literal["warning", "critical"]

    @model_validator(mode="after")
    def _value_fits_op(self) -> Rule:
        v = self.value
        is_number = isinstance(v, int | float) and not isinstance(v, bool)
        if self.op == "in":
            if not isinstance(v, list) or not 1 <= len(v) <= MAX_FIELDS:
                raise ValueError(f"op 'in' needs a list of 1 to {MAX_FIELDS} values")
        elif isinstance(v, list):
            raise ValueError(f"op '{self.op}' needs a single value")
        elif self.op in ("lt", "le", "gt", "ge", "delta_gt") and not is_number:
            raise ValueError(f"op '{self.op}' needs a number")
        elif self.op == "max_age" and not (is_number and v > 0):
            raise ValueError("op 'max_age' needs a positive number of seconds")
        return self


class Credential(_Model):
    # Becomes the reference <module id>/<instance key>/<slot> when an instance is adopted.
    slot: str = Field("default", pattern=_KEY)
    use: str = Field(pattern=r"^(bearer|basic|redis_auth|header:[A-Za-z0-9-]{1,64})$")


class Check(_Model):
    key: str = Field(pattern=_KEY)
    name: str = Field(min_length=1, max_length=128)
    sensor: str
    target: Target | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    interval: StrictInt
    timeout_s: int = Field(10, ge=1, le=30, strict=True)
    fields: list[str] = Field(min_length=1, max_length=MAX_FIELDS)
    rules: list[Rule] = Field(default_factory=list, max_length=MAX_FIELDS)
    credential: Credential | None = None
    # Makes the service do real work (a test mail, a test query): at most every 15 min.
    test_object: StrictBool = False
    # Binds only to a container whose image tag matches one of the globs (Wiki.js 2 has
    # /healthz, 3 not).
    image_tags: list[_TAG_GLOB] | None = Field(None, min_length=1, max_length=8)

    @field_validator("sensor")
    @classmethod
    def _known_sensor(cls, v: str) -> str:
        if v not in SENSORS:
            raise ValueError(f"unknown sensor {v!r}")
        return v

    @field_validator("interval")
    @classmethod
    def _allowed_interval(cls, v: int) -> int:
        if v not in INTERVALS:
            raise ValueError(f"interval must be one of {INTERVALS}")
        return v

    @field_validator("fields")
    @classmethod
    def _field_names(cls, v: list[str]) -> list[str]:
        for f in v:
            if len(f) > 128 or not FIELD_PATTERN.fullmatch(f):
                raise ValueError(f"invalid field name {f!r}")
        if len(set(v)) != len(v):
            raise ValueError("duplicate field names")
        return v

    @model_validator(mode="before")
    @classmethod
    def _params_of_sensor(cls, data: Any) -> Any:
        # Before, so the stored params carry the sensor's defaults and a foreign
        # key fails with the sensor's own message.
        if isinstance(data, dict) and data.get("sensor") in SENSORS:
            data = {**data, "params": validate_params(data["sensor"], data.get("params") or {})}
        return data

    @model_validator(mode="after")
    def _consistent(self) -> Check:
        if self.test_object and self.interval < TEST_OBJECT_MIN_INTERVAL:
            raise ValueError(
                f"a test object runs at most every {TEST_OBJECT_MIN_INTERVAL} s, "
                f"interval {self.interval} is shorter"
            )
        if self.image_tags is not None and (self.target is None or self.target.kind != "container"):
            raise ValueError("image_tags need a container target")
        kinds = SENSOR_TARGETS[self.sensor]
        if kinds is None and self.target is not None:
            raise ValueError(f"sensor {self.sensor!r} takes no target")
        if kinds is not None:
            if self.target is None:
                raise ValueError(f"sensor {self.sensor!r} needs a target")
            if self.target.kind not in kinds:
                raise ValueError(
                    f"sensor {self.sensor!r} cannot target {self.target.kind!r}, "
                    f"only {sorted(kinds)}"
                )
            if self.sensor == "app":
                view = self.params["view"]
                if self.target.kind not in APP_VIEW_TARGETS[view]:
                    raise ValueError(
                        f"view {view!r} of sensor 'app' targets only "
                        f"{sorted(APP_VIEW_TARGETS[view])}, not {self.target.kind!r}"
                    )
        for f in self.fields:
            if not field_allowed(self.sensor, f, self.params):
                raise ValueError(f"sensor {self.sensor!r} returns no field {f!r}")
        for rule in self.rules:
            if rule.field not in self.fields:
                raise ValueError(f"rule field {rule.field!r} is not among the check's fields")
        return self


class CardItem(_Model):
    check_key: str = Field(pattern=_KEY)
    field: str
    label: str = Field(min_length=1, max_length=64)


class Module(_Model):
    id: str = Field(pattern=_SLUG)
    name: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1, strict=True)
    description: str = Field("", max_length=1000)
    detect: Detect = Field(default_factory=Detect)
    instance: Literal["compose_project", "container", "unit", "process", "port"]
    checks: list[Check] = Field(min_length=1, max_length=50)
    card: list[CardItem] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _consistent(self) -> Module:
        # The port module stands for every listening port no other module claims.
        if self.instance != "port" and self.detect.is_empty():
            raise ValueError("a module needs at least one detection criterion")
        for marker in self.detect.markers:
            if not marker.id.startswith(f"{self.id}."):
                raise ValueError(f"marker id {marker.id!r} must start with '{self.id}.'")
        marker_ids = [m.id for m in self.detect.markers]
        if len(set(marker_ids)) != len(marker_ids):
            raise ValueError("duplicate marker ids")
        keys = [c.key for c in self.checks]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate check keys")
        by_key = {c.key: c for c in self.checks}
        # The agent binds a credential to the target it goes to first and refuses it to any
        # other (probe.go bindingOf), so the checks of one slot must ask the same target.
        slot_targets: dict[str, tuple[str, tuple]] = {}
        for check in self.checks:
            if check.credential is None:
                continue
            path = check.params.get("path") if check.sensor == "unixsocket" else None
            target = check.target.model_dump() if check.target else None
            seen = (check.key, (check.sensor, check.credential.use, target, path))
            first = slot_targets.setdefault(check.credential.slot, seen)
            if first[1] != seen[1]:
                raise ValueError(
                    f"checks {first[0]!r} and {check.key!r} share credential slot "
                    f"{check.credential.slot!r} but differ in sensor, use or target"
                )
        for check in self.checks:
            if check.target and check.target.service and self.instance != "compose_project":
                raise ValueError(
                    f"check {check.key!r}: target.service needs instance 'compose_project'"
                )
        for item in self.card:
            check = by_key.get(item.check_key)
            if check is None:
                raise ValueError(f"card names unknown check {item.check_key!r}")
            if item.field not in check.fields:
                raise ValueError(f"card field {item.field!r} is not among {item.check_key!r}'s")
        return self
