# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""pytest plugin for schemathesis_determinism.sh: one protocol line per case.

Loaded with ``-p schemathesis_curl_log`` (scripts/tests on PYTHONPATH). It wraps
``schemathesis.Case.call_and_validate`` and appends every case a suite sends to
``$AH_CURL_LOG`` as one JSON line ``[test id, curl command]`` — the test files stay
untouched. The curl command carries only what the case itself generated: the auth
headers a suite passes in are per-run values, not generated data, and would make two
identical runs differ. Without ``AH_CURL_LOG`` the plugin does nothing.

Rendered like ``Case.as_curl_command()`` but with sanitization off: that method masks
generated values of headers, query parameters and cookies with sensitive-looking names
(key, token, auth, …) as ``[Filtered]``, and a difference there would go unseen.
``prepare_request``/``curl.generate`` are what ``as_curl_command`` calls in the pinned
schemathesis. A release that moves them fails the import, and with it the run; one that
only changes a signature lands in the fallback below for every case, which still
measures, but only the case fields instead of the rendered request.
"""

import json
import os

import schemathesis
from schemathesis.config import SanitizationConfig
from schemathesis.core import curl
from schemathesis.transport.prepare import prepare_request

_LOG = os.environ.get("AH_CURL_LOG")
_UNFILTERED = SanitizationConfig(enabled=False)


def _curl(case) -> str:
    try:
        request = prepare_request(case, None, config=_UNFILTERED)
        return curl.generate(
            method=str(request.method),
            url=str(request.url),
            body=request.body,
            verify=True,
            headers=dict(request.headers),
            known_generated_headers=dict(case.headers or {}),
        ).command
    except Exception as exc:  # a case curl cannot express still has to be counted
        fields = (case.method, case.formatted_path, case.query, case.headers, case.body)
        return f"<{type(exc).__name__}> {fields!r}"


def pytest_configure(config):
    if not _LOG:
        return
    original = schemathesis.Case.call_and_validate

    def call_and_validate(self, *args, **kwargs):
        test = os.environ.get("PYTEST_CURRENT_TEST", "?").rsplit(" (", 1)[0]
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps([test, _curl(self)], ensure_ascii=False) + "\n")
        return original(self, *args, **kwargs)

    schemathesis.Case.call_and_validate = call_and_validate
