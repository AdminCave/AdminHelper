# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reads the catalog modules, checks them and gives the catalog its version.

An invalid module is left out and named in `Catalog.errors`, it does not stop the
service: the catalog test fails on any error, so a broken entry never ships, and a
running service keeps monitoring with the modules that are fine.

`version` is the SHA-256 over the canonical JSON of all modules as checked (defaults
filled in). It changes with every change a module makes to the plan or the checks,
and the agent's plan carries it, so both sides can tell which catalog a check came from.
"""

from __future__ import annotations

import functools
import hashlib
import importlib
import json
import logging
import pkgutil
from collections.abc import Iterable
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.catalog import modules as _modules_pkg
from app.catalog.model import Module

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Catalog:
    modules: dict[str, Module]
    version: str
    errors: tuple[str, ...] = field(default=())


def _shipped_modules() -> tuple[list[tuple[str, object]], list[str]]:
    found: list[tuple[str, object]] = []
    errors: list[str] = []
    for info in sorted(pkgutil.iter_modules(_modules_pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{_modules_pkg.__name__}.{info.name}")
        except Exception as exc:  # a module file that does not import is left out too
            errors.append(f"{info.name}: import failed: {type(exc).__name__}: {exc}")
            continue
        found.append((info.name, getattr(mod, "MODULE", None)))
    return found, errors


def _error_text(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'module'}: {e['msg']}" for e in exc.errors()
    )


def catalog_version(modules: Iterable[Module]) -> str:
    canonical = json.dumps(
        [m.model_dump(mode="json") for m in sorted(modules, key=lambda m: m.id)],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_catalog(raw_modules: Iterable[tuple[str, object]] | None = None) -> Catalog:
    """Check `raw_modules` (source name, MODULE dict); without them the shipped ones."""
    modules: dict[str, Module] = {}
    errors: list[str] = []
    if raw_modules is None:
        raw_modules, errors = _shipped_modules()
    for source, raw in raw_modules:
        if not isinstance(raw, dict):
            errors.append(f"{source}: MODULE is missing or not a dict")
            continue
        try:
            module = Module.model_validate(raw)
        except ValidationError as exc:
            errors.append(f"{source}: {_error_text(exc)}")
            continue
        if module.id in modules:
            errors.append(f"{source}: duplicate module id {module.id!r}")
            continue
        modules[module.id] = module
    for error in errors:
        log.error("catalog module left out: %s", error)
    return Catalog(
        modules=dict(sorted(modules.items())),
        version=catalog_version(modules.values()),
        errors=tuple(errors),
    )


@functools.cache
def get_catalog() -> Catalog:
    return load_catalog()
