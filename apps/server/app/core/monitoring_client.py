# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The server's calls to the monitoring service: one place for its base URL and the internal key.

Config is read at call time, so a test that patches app.core.config sees every caller follow.
"""

import httpx

from app.core import config


def base_url() -> str:
    # A trailing slash in MONITOR_SERVICE_URL would yield `//path`, which the monitoring's
    # no-prefix routes answer with 404 (R-0691).
    return config.MONITOR_SERVICE_URL.rstrip("/")


def url(path: str) -> str:
    return f"{base_url()}{path}"


def request(method: str, path: str, *, timeout: float | httpx.Timeout) -> httpx.Response:
    return httpx.request(
        method,
        url(path),
        headers={"X-Internal-Key": config.MONITOR_API_KEY},
        timeout=timeout,
    )
