# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read numeric settings from the environment, refusing invalid values.

One rule for both services: an unset or empty variable takes its default, a set one must
be valid or the service stops at start with a message naming the variable, its value and
what was expected. A typo that silently became the default used to surface much later
as behaviour nobody configured.
"""

import os


class ConfigError(ValueError):
    """A configuration variable holds a value the service cannot run with."""


def parse_int(
    name: str,
    raw: str | None,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Parses ``raw`` as the value of ``name``; empty or ``None`` gives ``default``."""
    value = (raw or "").strip()
    if not value:
        return default
    if minimum is not None and maximum is not None:
        expected = f"a whole number between {minimum} and {maximum}"
    elif minimum is not None:
        expected = f"a whole number >= {minimum}"
    elif maximum is not None:
        expected = f"a whole number <= {maximum}"
    else:
        expected = "a whole number"
    try:
        number = int(value)
    except ValueError:
        raise ConfigError(f"{name}={raw!r} is not {expected}") from None
    if (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        raise ConfigError(f"{name}={raw!r} is not {expected}")
    return number


def env_int(
    name: str, default: int, *, minimum: int | None = None, maximum: int | None = None
) -> int:
    """Reads ``name`` from the environment as with :func:`parse_int`."""
    return parse_int(name, os.environ.get(name), default, minimum=minimum, maximum=maximum)
