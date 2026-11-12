# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Writes tests/shard_weights.toml from the JUnit XML of a CI run of the server suite (R-1341).

In apps/server, with the XML of every shard of one leg (artifacts junit-server-py3.14-*):

    python -m tests.shard_weights <source> <junit.xml>... > tests/shard_weights.toml

<source> names the run in the header of the table, a URL or a short note.
"""

import sys
import xml.etree.ElementTree as ElementTree
from collections import defaultdict


def file_of(classname: str) -> str:
    """tests.test_x or tests.test_x.TestY -> tests/test_x.py, as in the node IDs of pytest."""
    package, module = classname.split(".")[:2]
    return f"{package}/{module}.py"


def measure(paths: list[str]) -> dict[str, tuple[float, int]]:
    """Seconds (setup, call and teardown) and tests of each test file the XML reports."""
    seconds: dict[str, float] = defaultdict(float)
    tests: dict[str, int] = defaultdict(int)
    for path in paths:
        for case in ElementTree.parse(path).iter("testcase"):
            name = file_of(case.get("classname", ""))
            seconds[name] += float(case.get("time", "0"))
            tests[name] += 1
    return {name: (seconds[name], tests[name]) for name in sorted(tests)}


# REUSE-IgnoreStart
_HEADER = """\
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Seconds and tests of each file of the server suite in one CI run; --shard weighs a file
# with its seconds per test (conftest.py, R-1341). Written by, in apps/server:
#   python -m tests.shard_weights <source> <junit.xml>... > tests/shard_weights.toml
# Source: {source}
"""
# REUSE-IgnoreEnd


def render(source: str, files: dict[str, tuple[float, int]]) -> str:
    lines = [_HEADER.format(source=source), "[files]"]
    lines += [
        f'"{name}" = {{ seconds = {seconds:.3f}, tests = {tests} }}'
        for name, (seconds, tests) in files.items()
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    sys.stdout.write(render(argv[0], measure(argv[1:])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
