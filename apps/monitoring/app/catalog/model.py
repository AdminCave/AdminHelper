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
    model_serializer,
    model_validator,
)

from app.catalog.sensors import (
    APP_VIEW_TARGETS,
    FIELD_PATTERN,
    OPTIONAL_TARGET_SENSORS,
    PASSWORD_VIEWS,
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


# The applications the agent recognises in the document root of a vhost (web_vhosts.go webApp).
VHOST_APPS = ("nextcloud", "moodle", "wordpress", "bookstack")


class Detect(_Model):
    container_images: list[_NAME_ITEM] = Field(default_factory=list, max_length=32)
    units: list[_NAME_ITEM] = Field(default_factory=list, max_length=32)
    processes: list[_NAME_ITEM] = Field(default_factory=list, max_length=32)
    markers: list[Marker] = Field(default_factory=list, max_length=16)
    # Hints only: a port is never assumed, the agent asks the one really listening.
    port_hints: list[_PORT] = Field(default_factory=list, max_length=16)
    # False for a module that checks no port of its units (nginx on 443): those ports stay
    # port findings, which ask whether they answer.
    claims_unit_ports: StrictBool = True
    # True for a oneshot unit a timer starts (a backup job): between its runs it is inactive
    # and still in use, so an inactive unit makes an instance too.
    idle_units: StrictBool = False
    # For a module with instance "vhost": only vhosts with TLS, only vhosts of these applications.
    vhost_tls: StrictBool = False
    vhost_apps: list[Literal[VHOST_APPS]] = Field(default_factory=list, max_length=len(VHOST_APPS))
    # For a module with instance "share": every network share the agent finds mounted.
    net_shares: StrictBool = False

    def is_empty(self) -> bool:
        return not (self.container_images or self.units or self.processes or self.markers)

    def by_vhost(self) -> bool:
        return self.vhost_tls or bool(self.vhost_apps)


class Alternative(_Model):
    port_hint: _PORT
    scheme: Literal["http", "https", "tcp", "auto"]


class Target(_Model):
    kind: Literal["loopback", "container", "process", "unit", "port", "vhost", "share"]
    # Compose service of the instance's project whose container the check asks.
    service: str = Field("", max_length=255)
    # Without the service: the one container of the instance with the module's image that
    # no other check's service names (Nextcloud started by `docker run` or as `nextcloud`).
    image_fallback: StrictBool = False
    port_hint: _PORT | None = None
    # auto: the http sensor asks the port whether it speaks TLS (field tls).
    scheme: Literal["http", "https", "tcp", "auto"] | None = None
    # In order: the first whose port the last scan saw at the container (Bitwarden's nginx
    # listens on 8443 with TLS and redirects 8080 there, on 8080 alone without).
    alternatives: list[Alternative] | None = Field(None, min_length=1, max_length=4)

    @model_validator(mode="after")
    def _consistent(self) -> Target:
        if self.image_fallback and not self.service:
            raise ValueError("image_fallback needs a service")
        if self.alternatives is not None:
            if self.kind not in ("container", "loopback", "unit"):
                raise ValueError("alternatives need a container, loopback or unit target")
            if self.port_hint is not None or self.scheme is not None:
                raise ValueError("alternatives replace port_hint and scheme")
        return self


class RuleUnless(_Model):
    field: str
    value: _Scalar


COMPARE_OPS = ("lt", "le", "gt", "ge")
# A sibling's result may be up to a week old before a condition on it counts as unknown.
CONDITION_MAX_AGE = 7 * 86400


def _is_number(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _value_fits(op: str, v: object, what: str) -> None:
    if op == "in":
        if not isinstance(v, list) or not 1 <= len(v) <= MAX_FIELDS:
            raise ValueError(f"{what}op 'in' needs a list of 1 to {MAX_FIELDS} values")
    elif isinstance(v, list):
        raise ValueError(f"{what}op '{op}' needs a single value")
    elif op in (*COMPARE_OPS, "delta_gt") and not _is_number(v):
        raise ValueError(f"{what}op '{op}' needs a number")


def clear_fits(op: str, value: object, clear: object) -> bool:
    """Whether `clear` lies strictly on the good side of the limit: below it for gt/ge, above
    it for lt/le. Only a compare operator with a number has a side."""
    if op not in COMPARE_OPS or not _is_number(value) or not _is_number(clear):
        return False
    return clear < value if op in ("gt", "ge") else clear > value


class Condition(_Model):
    """What a rule waits for (R-1638, ADR 0004 §6.4): a field of the same result, or with
    `check` of another probe check of the module at the same instance."""

    field: str
    op: Literal["eq", "ne", "in", "lt", "le", "gt", "ge"]
    value: _Scalar | list[_Scalar]
    check: str | None = Field(None, pattern=_KEY)
    # Seconds; an older result of the other check counts as unknown.
    max_age: int | None = Field(None, ge=1, le=CONDITION_MAX_AGE, strict=True)

    @model_serializer(mode="wrap")
    def _options_only_when_set(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        for key in ("check", "max_age"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

    @model_validator(mode="after")
    def _value_fits_op(self) -> Condition:
        _value_fits(self.op, self.value, "when: ")
        if self.max_age is not None and self.check is None:
            # The own result is always the one being rated, so it is never too old.
            raise ValueError("when: max_age needs a check")
        return self


class Rule(_Model):
    field: str
    # delta_gt: rose by more than value since the run before; drop_pct_gt: fell by more than
    # value percent since the run before (a backup file half the size of the last one).
    op: Literal["eq", "ne", "lt", "le", "gt", "ge", "in", "max_age", "delta_gt", "drop_pct_gt"]
    value: _Scalar | list[_Scalar]
    # info: a hint without an alarm (R-1280): the check shows it, nothing notifies.
    level: Literal["info", "warning", "critical"]
    # Kevin 2026-11-16 (R-1475): the agent leaves a field out when there is nothing to rate
    # (no replication link, no certificate, no license pack); that is ok, not unknown.
    if_absent: Literal["ok"] | None = None
    # The rule does not apply while another field of the same result has this value
    # (R-1480: Defender's real-time protection in passive mode).
    unless: RuleUnless | None = None
    # The rule's name in the admin's overrides and in a catalog merge (R-1638); without one
    # it is <field>.<level> (rule_key).
    key: str | None = Field(None, pattern=_KEY)
    # Hysteresis: once the rule fires it holds until the value passes clear.
    clear: StrictInt | StrictFloat | None = None
    # The rule rates only while the condition holds or cannot be told.
    when: Condition | None = None

    @model_serializer(mode="wrap")
    def _options_only_when_set(self, handler: Any) -> dict[str, Any]:
        # Left out when unset, so the modules that do not use them keep their hash.
        data = handler(self)
        for key in ("if_absent", "unless", "key", "clear", "when"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

    @model_validator(mode="after")
    def _value_fits_op(self) -> Rule:
        v = self.value
        _value_fits(self.op, v, "")
        if self.op == "drop_pct_gt" and not (_is_number(v) and 0 < v < 100):
            raise ValueError("op 'drop_pct_gt' needs a percentage between 0 and 100")
        if self.op == "max_age" and not (_is_number(v) and v > 0):
            raise ValueError("op 'max_age' needs a positive number of seconds")
        if self.clear is not None:
            if self.op not in COMPARE_OPS:
                raise ValueError(f"clear needs op lt, le, gt or ge, not {self.op!r}")
            if not clear_fits(self.op, v, self.clear):
                side = "below" if self.op in ("gt", "ge") else "above"
                raise ValueError(f"clear must lie {side} the limit {v}")
        return self


def rule_key(rule: Rule) -> str:
    return rule.key or f"{rule.field}.{rule.level}"


def rule_problems(rules: list[Rule]) -> list[str]:
    """Why the rules of one check do not hold as a set; each rule checks itself."""
    problems: list[str] = []
    seen: set[str] = set()
    for rule in rules:
        key = rule_key(rule)
        if key in seen:
            problems.append(f"rule key {key!r} is given twice")
        seen.add(key)
    return problems


class Credential(_Model):
    # Becomes the reference <module id>/<instance key>/<slot> when an instance is adopted.
    slot: str = Field("default", pattern=_KEY)
    use: str = Field(
        pattern=r"^(bearer|basic|redis_auth|redis_acl|password|header:[A-Za-z0-9-]{1,64})$"
    )
    # Kevin 2026-11-14 (R-1264): the check runs without it while the host has none stored,
    # and reads more with it (Redis and many web services run without a password).
    optional: StrictBool = False

    @model_serializer(mode="wrap")
    def _optional_only_when_set(self, handler: Any) -> dict[str, Any]:
        # Left out when false, so the modules that do not use it keep their hash.
        data = handler(self)
        if not self.optional:
            data.pop("optional", None)
        return data


class Check(_Model):
    key: str = Field(pattern=_KEY)
    name: str = Field(min_length=1, max_length=128)
    sensor: str
    target: Target | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    interval: StrictInt
    timeout_s: int = Field(10, ge=1, le=30, strict=True)
    fields: list[str] = Field(default_factory=list, max_length=MAX_FIELDS)
    rules: list[Rule] = Field(default_factory=list, max_length=MAX_FIELDS)
    credential: Credential | None = None
    # Makes the service do real work (a test mail, a test query): at most every 15 min.
    test_object: StrictBool = False
    # Binds only to a container whose image tag matches one of the globs (Wiki.js 2 has
    # /healthz, 3 not).
    image_tags: list[_TAG_GLOB] | None = Field(None, min_length=1, max_length=8)
    # Run by the monitoring service against the instance's public name with a sensor of
    # CENTRAL_SENSORS, never by the agent; it rates itself, so no fields or rules (R-1501).
    central: StrictBool = False
    # Bound only at the instance with this key, at no other (R-1528): a check of the host
    # in a module whose instances are its units (the web interface of 3CX).
    instance: str | None = Field(None, min_length=1, max_length=255)

    @model_serializer(mode="wrap")
    def _options_only_when_set(self, handler: Any) -> dict[str, Any]:
        # Left out when unset, so the checks that do not use them keep their hash.
        data = handler(self)
        if not self.central:
            data.pop("central", None)
        if self.instance is None:
            data.pop("instance", None)
        return data

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
        if not isinstance(data, dict):
            return data
        sensor = data.get("sensor")
        if data.get("central") is True:
            # Imported here: check_configs imports this module.
            from app.check_configs import CENTRAL_SENSORS

            if sensor in CENTRAL_SENSORS:
                params = CENTRAL_SENSORS[sensor].params.model_validate(data.get("params") or {})
                data = {**data, "params": params.model_dump(mode="json", exclude_unset=True)}
        elif sensor in SENSORS:
            data = {**data, "params": validate_params(sensor, data.get("params") or {})}
        return data

    def _central_consistent(self) -> Check:
        from app.check_configs import CENTRAL_SENSORS
        from app.scheduler import interval_timedelta

        sensor = CENTRAL_SENSORS.get(self.sensor)
        if sensor is None:
            raise ValueError(
                f"unknown central sensor {self.sensor!r}, only {sorted(CENTRAL_SENSORS)}"
            )
        if self.target is None or self.target.kind != "vhost":
            # The host of a central check is the instance's name; only a vhost is one.
            raise ValueError("a central check targets the vhost")
        if (
            self.fields
            or self.rules
            or self.credential is not None
            or self.test_object
            or self.image_tags is not None
        ):
            raise ValueError(
                "a central check rates itself: no fields, rules, credential, test_object "
                "or image_tags"
            )
        shortest = int(interval_timedelta(sensor.min_interval).total_seconds())
        if self.interval < shortest:
            raise ValueError(
                f"the central sensor {self.sensor!r} runs at most every {shortest} s, "
                f"interval {self.interval} is shorter"
            )
        return self

    @model_validator(mode="after")
    def _consistent(self) -> Check:
        if self.central:
            return self._central_consistent()
        if self.sensor not in SENSORS:
            raise ValueError(f"unknown sensor {self.sensor!r}")
        if not self.fields:
            raise ValueError("fields: a check needs at least one field")
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
        if kinds is not None and self.target is None:
            if self.sensor not in OPTIONAL_TARGET_SENSORS:
                raise ValueError(f"sensor {self.sensor!r} needs a target")
        elif kinds is not None:
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
        if self.target is not None and self.sensor != "http":
            schemes = [self.target.scheme] + [a.scheme for a in self.target.alternatives or []]
            if "auto" in schemes:
                # Only the http sensor asks the port; any other would take auto for a scheme.
                raise ValueError(f"scheme 'auto' only for sensor 'http', not {self.sensor!r}")
        if (
            self.credential is not None
            and self.credential.use == "password"
            and not (self.sensor == "app" and self.params["view"] in PASSWORD_VIEWS)
        ):
            # The agent hands a password only to a repository's own command, as its
            # environment; any other sensor would send it somewhere.
            raise ValueError(
                f"credential use 'password' only for the views {sorted(PASSWORD_VIEWS)}"
            )
        for f in self.fields:
            if not field_allowed(self.sensor, f, self.params):
                raise ValueError(f"sensor {self.sensor!r} returns no field {f!r}")
        for rule in self.rules:
            if rule.field not in self.fields:
                raise ValueError(f"rule field {rule.field!r} is not among the check's fields")
            if rule.unless is not None and rule.unless.field not in self.fields:
                raise ValueError(
                    f"unless field {rule.unless.field!r} is not among the check's fields"
                )
            when = rule.when
            if when is not None and when.check is None and when.field not in self.fields:
                raise ValueError(f"when field {when.field!r} is not among the check's fields")
        keys = [rule_key(rule) for rule in self.rules]
        for rule, key in zip(self.rules, keys, strict=True):
            # The hysteresis is kept by key: two rules under one key would hold each other.
            # A stored config from before keys may name two rules alike, but none has clear.
            if rule.clear is not None and keys.count(key) > 1:
                raise ValueError(
                    f"rule key {key!r} is given twice; a rule with clear needs its own"
                )
        return self


def _sibling_fits(check: Check, rule: Rule, by_key: dict[str, Check]) -> None:
    # The server reads the other check's result at the same instance only (R-1638).
    when = rule.when
    where = f"check {check.key!r}, rule {rule_key(rule)!r}"
    other = by_key.get(when.check)
    if other is None or other is check:
        raise ValueError(f"{where}: when.check {when.check!r} names no other check of the module")
    if when.field not in other.fields:
        raise ValueError(f"{where}: when field {when.field!r} is not among {other.key!r}'s fields")
    if other.instance is not None and other.instance != check.instance:
        # The other check is bound at one instance only; at the rest it would never report.
        raise ValueError(f"{where}: {other.key!r} is bound only at instance {other.instance!r}")


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
    instance: Literal["compose_project", "container", "unit", "process", "port", "vhost", "share"]
    checks: list[Check] = Field(min_length=1, max_length=50)
    card: list[CardItem] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _consistent(self) -> Module:
        # The port module stands for every listening port no other module claims.
        if self.instance == "vhost":
            # A vhost is found by its name alone; a stand-in from a unit or a marker would be
            # an instance with no name to ask.
            if not self.detect.by_vhost() or not self.detect.is_empty():
                raise ValueError(
                    "a module with instance 'vhost' detects by vhost_tls or vhost_apps only"
                )
        elif self.instance == "share":
            # A share is found by its mount point alone, like a vhost by its name.
            if not self.detect.net_shares or not self.detect.is_empty() or self.detect.by_vhost():
                raise ValueError("a module with instance 'share' detects by net_shares only")
        elif self.detect.by_vhost():
            raise ValueError("vhost_tls and vhost_apps need instance 'vhost'")
        elif self.detect.net_shares:
            raise ValueError("net_shares needs instance 'share'")
        elif self.instance != "port" and self.detect.is_empty():
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
            if check.central and self.instance != "vhost":
                raise ValueError(f"check {check.key!r}: a central check needs instance 'vhost'")
            if check.target and check.target.kind == "share" and self.instance != "share":
                raise ValueError(f"check {check.key!r}: target 'share' needs instance 'share'")
            if (
                check.instance is not None
                and self.instance == "unit"
                and check.instance not in self.detect.units
            ):
                raise ValueError(
                    f"check {check.key!r}: instance {check.instance!r} is none of the module's units"
                )
            if check.target and check.target.service and self.instance != "compose_project":
                raise ValueError(
                    f"check {check.key!r}: target.service needs instance 'compose_project'"
                )
            # Here and not in Check: a stored probe config is checked as a Check too, and one
            # stored before keys existed may name two rules alike (R-1638).
            problems = rule_problems(list(check.rules))
            if problems:
                raise ValueError(f"check {check.key!r}: {problems[0]}")
            for rule in check.rules:
                if rule.when is not None and rule.when.check is not None:
                    _sibling_fits(check, rule, by_key)
        for item in self.card:
            check = by_key.get(item.check_key)
            if check is None:
                raise ValueError(f"card names unknown check {item.check_key!r}")
            if item.field not in check.fields:
                raise ValueError(f"card field {item.field!r} is not among {item.check_key!r}'s")
        return self
