# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hook examples call the worker's HTTP helpers with keywords the helpers accept.

docs/examples/*.py are the starting points admins copy into hook scripts. They run
inside script_worker.py, which binds http_get/http_post to _safe_http_get and
_safe_http_post. Neither takes **kwargs, so a keyword the signature does not name
is a TypeError at runtime. event_hook_notify.py passed json= and its except branch
logged that TypeError as a failed notification (R-0490). No test executes the
examples, so the drift stayed invisible; this one compares each call against the
signature the worker really injects.

The examples also carry addresses, and those stay within the documentation networks of
RFC 5737, so a copied example never points at a real host.
"""

import ast
import inspect
import ipaddress
import re
from pathlib import Path

from app.modules.hooks import script_worker

_ROOT = Path(__file__).resolve().parents[3]
_EXAMPLES_DIR = _ROOT / "docs" / "examples"

# Name in the hook namespace -> the function script_worker.main() binds to it.
_HELPERS = {
    "http_get": script_worker._safe_http_get,
    "http_post": script_worker._safe_http_post,
}


def test_example_http_helper_keywords_match_worker_signature():
    examples = sorted(_EXAMPLES_DIR.glob("*.py"))
    # An empty glob or a run without a single helper call would pass vacuously.
    assert examples, f"no hook examples under {_EXAMPLES_DIR}"

    allowed = {name: list(inspect.signature(fn).parameters) for name, fn in _HELPERS.items()}
    calls = 0
    problems = []
    for path in examples:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in _HELPERS
            ):
                continue
            calls += 1
            helper = node.func.id
            for kw in node.keywords:
                if kw.arg in allowed[helper]:
                    continue
                arg = kw.arg if kw.arg is not None else f"**{ast.unparse(kw.value)}"
                problems.append(
                    f"{path.relative_to(_ROOT)}:{kw.lineno}: {helper}() has no parameter "
                    f"{arg!r}; allowed: {', '.join(allowed[helper])}"
                )

    assert calls, f"no http_get/http_post call in {_EXAMPLES_DIR}"
    assert not problems, "\n".join(problems)


_DOTTED_QUAD = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_DOC_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]


def _foreign_ipv4(text: str) -> list[str]:
    """Every dotted quad in text that is no address of an RFC 5737 network."""
    found = []
    for quad in _DOTTED_QUAD.findall(text):
        try:
            addr = ipaddress.IPv4Address(quad)
        except ipaddress.AddressValueError:
            found.append(quad)
            continue
        if not any(addr in net for net in _DOC_NETS):
            found.append(quad)
    return found


def test_examples_use_only_rfc5737_addresses():
    files = sorted(p for p in _EXAMPLES_DIR.rglob("*") if p.is_file())
    assert files, f"no hook examples under {_EXAMPLES_DIR}"
    problems = [
        f"{path.relative_to(_ROOT)}: {quad}"
        for path in files
        for quad in _foreign_ipv4(path.read_text(encoding="utf-8"))
    ]
    assert not problems, problems


def test_foreign_ipv4_flags_addresses_outside_the_documentation_networks():
    assert _foreign_ipv4("a 198.18.0.1 b 8.8.8.8") == ["198.18.0.1", "8.8.8.8"]
    assert _foreign_ipv4("192.0.2.1 198.51.100.7 203.0.113.255 1.2.3") == []
