# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ci_changes.py maps the paths a pull request changes to the suites of ci.yml (R-1340).

A pull request skips a suite only when none of its paths lies in the suite's scope, so a scope
has to name every file the suite reads. These tests hold the scopes, the jobs of ci.yml and the
suites' own sources in step: every file under apps/ belongs to a gated suite or to a job that
always runs, every job of ci.yml is gated, a gate or always on, and every path the Python suites
name in their source lies in the scope of their suite.

The tree is read from disk, not from git: on a test box synced from a worktree .git is a dead
pointer (scripts/vm/rsync-exclude.txt).
"""

import ast
import functools
import importlib.util
import json
import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from .test_ci_workflow import _evaluate, _git

_ROOT = Path(__file__).resolve().parents[3]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_SCRIPT = _ROOT / ".github" / "scripts" / "ci_changes.py"


def _load():
    spec = importlib.util.spec_from_file_location("ci_changes", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci_changes = _load()
_SCOPES = ci_changes.SCOPES

# Build output, caches, runtime data and the private repository: not part of the tree.
_PRUNE = {
    ".git",
    ".ah-out",
    ".cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svelte-kit",
    ".turbo",
    ".venv",
    ".vm",
    "__pycache__",
    "backups",
    "binaries",
    "coverage",
    "dist",
    "node_modules",
    "playwright-report",
    "target",
    "test-results",
}
_PRUNE_PATHS = {"apps/server/data", "tasks/private"}


@functools.cache
def _tree() -> tuple[str, ...]:
    files = []
    for top, dirs, names in os.walk(_ROOT):
        rel = Path(top).relative_to(_ROOT)
        dirs[:] = [d for d in dirs if d not in _PRUNE and (rel / d).as_posix() not in _PRUNE_PATHS]
        files += [(rel / name).as_posix() for name in names]
    return tuple(sorted(files))


# --- the mapping ---------------------------------------------------------------------------

_NONE = {name: "false" for name in _SCOPES}
_ALL = {name: "true" for name in _SCOPES}


def _on(*names: str) -> dict:
    assert set(names) <= set(_SCOPES), names
    return {**_NONE, **{name: "true" for name in names}}


@pytest.mark.parametrize(
    ("paths", "want"),
    [
        (["docs/admin/users.html"], _on()),
        (["tasks/x.md", "changelog.d/x.md"], _on()),
        (["docs/examples/hooks/notify.py"], _on("server")),
        (["docs/en/developer/monitoring.html"], _on("server")),
        (["apps/web/src/lib/api/client.ts"], _on("server")),
        (["apps/web/src/routes/+page.svelte"], _on()),
        (["apps/server/app/main.py"], _on("server", "schemathesis")),
        (["apps/server/tests/test_x.py"], _on("server", "schemathesis")),
        (["apps/server/requirements.txt"], _on("server", "schemathesis", "lock-server")),
        (
            ["apps/server/app/modules/notifications/schemas.py"],
            _on("server", "monitoring", "schemathesis"),
        ),
        (["apps/monitoring/app/main.py"], _on("server", "monitoring", "schemathesis")),
        (["apps/monitoring/tests/test_x.py"], _on("monitoring", "schemathesis")),
        (
            ["apps/monitoring/requirements.txt"],
            _on("server", "monitoring", "schemathesis", "lock-monitoring"),
        ),
        (
            ["apps/monitoring/Dockerfile"],
            _on("server", "monitoring", "schemathesis", "lock-monitoring"),
        ),
        (["apps/ca-issuer/tests/test_x.py"], _on("ca-issuer", "schemathesis")),
        (
            ["apps/ca-issuer/Dockerfile"],
            _on("server", "ca-issuer", "schemathesis", "lock-ca-issuer"),
        ),
        (
            ["apps/ca-issuer/requirements.in"],
            _on("server", "ca-issuer", "schemathesis", "lock-ca-issuer"),
        ),
        (["apps/agent/internal/frpspolicy/policy.go"], _on("server", "agent-windows")),
        (["apps/agent/internal/frpc/testdata/server_frpc.toml"], _on("server", "agent-windows")),
        (["apps/agent/internal/frpc/apply.go"], _on("agent-windows")),
        (["apps/agent/internal/monitor/hostfacts.go"], _on("monitoring", "agent-windows")),
        (["apps/agent/internal/credentials/store.go"], _on("agent-windows", "rust-windows")),
        (["apps/agent/internal/allowlist/allowlist.go"], _on("agent-windows", "rust-windows")),
        (["apps/agent/cmd/agent/main.go"], _on("agent-windows")),
        (["apps/desktop/src-tauri/src/tunnel.rs"], _on("server", "rust-windows")),
        (["apps/desktop/src-tauri/src/main.rs"], _on("rust-windows")),
        (["apps/desktop/ui/src/lib/models/monitoring.ts"], _on("monitoring")),
        (["apps/desktop/ui/src/App.svelte"], _on()),
        (["apps/gateway/nginx.conf"], _on("server")),
        (["apps/frps/Dockerfile"], _on("server")),
        (["docs/admin/users.html", "apps/frps/Dockerfile"], _on("server")),
        # Outside the narrow areas: the server image (root Dockerfile), the workflows, the
        # scripts, a component nobody mapped yet.
        (["Dockerfile"], _ALL),
        (["docs/index.html", ".github/workflows/ci.yml"], _ALL),
        (["scripts/tests/run.sh"], _ALL),
        (["apps/new-component/main.py"], _ALL),
        # A pull request without a changed path: nothing to narrow, everything runs.
        ([], _ALL),
    ],
)
def test_a_pull_request_runs_the_suites_whose_scope_its_paths_touch(paths, want):
    result, reasons = ci_changes.outputs("pull_request", paths)
    assert result == {**want, "server-legs": '["3.14"]'}
    assert len(reasons) == len(_SCOPES)


@pytest.mark.parametrize("event", ["push", "merge_group", "workflow_dispatch", "schedule"])
def test_every_other_event_runs_everything_on_both_legs(event):
    result, reasons = ci_changes.outputs(event, ["docs/admin/users.html"])
    assert result == {**_ALL, "server-legs": '["3.14","3.15"]'}
    assert all(f"event {event} runs everything" in reason for reason in reasons)


def test_the_legs_are_those_of_the_server_matrix():
    assert ci_changes.LEGS == ("3.14", "3.15")
    assert ci_changes.PR_LEGS == ("3.14",)
    server_result = yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]["server-result"]
    assert server_result["strategy"]["matrix"]["python-version"] == list(ci_changes.LEGS)


def test_every_file_of_the_tree_classifies():
    for path in _tree():
        result, _ = ci_changes.outputs("pull_request", [path])
        assert set(result.values()) <= {"true", "false", '["3.14"]'}, path
        if not ci_changes.matches(ci_changes.NARROW, path):
            assert result == {**_ALL, "server-legs": '["3.14"]'}, path


def test_the_last_pattern_that_matches_decides():
    patterns = ("apps/x/**", "!apps/x/tests/**", "apps/x/tests/keep.py")
    assert ci_changes.matches(patterns, "apps/x/app/main.py")
    assert not ci_changes.matches(patterns, "apps/x/tests/test_a.py")
    assert ci_changes.matches(patterns, "apps/x/tests/keep.py")
    assert not ci_changes.matches(patterns, "apps/y/main.py")
    # * stops at a /, ** does not.
    assert ci_changes.matches(("apps/*/Dockerfile",), "apps/x/Dockerfile")
    assert not ci_changes.matches(("apps/*/Dockerfile",), "apps/x/y/Dockerfile")
    assert ci_changes.matches(("apps/**/*.go",), "apps/x/y/z.go")


# --- the jobs of ci.yml --------------------------------------------------------------------

# job -> the output of changes that turns it off
_GATED = {
    "server": "server",
    "monitoring": "monitoring",
    "ca-issuer": "ca-issuer",
    "schemathesis": "schemathesis",
    "python-lock-server": "lock-server",
    "python-lock-monitoring": "lock-monitoring",
    "python-lock-ca-issuer": "lock-ca-issuer",
    "agent-windows": "agent-windows",
    "rust-windows": "rust-windows",
}
# The required checks of the sharded jobs: they always run and report a leg the changes did not
# ask for as green (test_ci_shards.py).
_GATES = {"server-result", "python-lock-server-result"}
# What the server image (context ., root .dockerignore), the images of apps/monitoring,
# apps/ca-issuer and apps/gateway (their directory as context) and the frps image (context .,
# apps/frps/Dockerfile.dockerignore) take from apps/.
_IMAGES = (
    "apps/server/**",
    "apps/web/**",
    "apps/monitoring/**",
    "apps/ca-issuer/**",
    "apps/gateway/**",
    "apps/frps/**",
    *ci_changes._FRPS_CONTEXT,
)
# job -> the files under apps/ it reads: the jobs that run on every pull request.
_ALWAYS_ON = {
    "python-lint": ("apps/**/*.py",),
    "agent": ("apps/agent/**",),
    "desktop-ui": ("apps/desktop/ui/**", "apps/desktop/e2e/**"),
    "frontend": ("apps/web/**",),
    "frontend-e2e": ("apps/web/**",),
    "rust": (
        "apps/desktop/src-tauri/**",
        "apps/agent/internal/credentials/store.go",
        "apps/agent/internal/allowlist/allowlist.go",
    ),
    "tauri-build-smoke": ("apps/desktop/ui/**", "apps/desktop/src-tauri/**"),
    "rdp-embedded": ("apps/desktop/src-tauri/**",),
    "docker-build": _IMAGES,
    "frp-consistency": ("apps/frps/Dockerfile",),
    "pkg-repo": (
        "apps/agent/build-common.sh",
        "apps/agent/build-pkg.sh",
        "apps/agent/freebsd/**",
        "apps/agent/opnsense/**",
    ),
    "openapi-compat": ("apps/server/**", "apps/monitoring/**"),
    # Reads every changed path and tests none of them.
    "public-repo-guard": (),
    "ops-scripts": ("apps/*/docker-entrypoint.sh", "apps/frps/frps-supervisor.sh"),
    "gateway-config": ("apps/gateway/**",),
    "integration-stack": _IMAGES,
}


def _jobs() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]


def test_every_job_of_ci_yml_is_gated_a_gate_or_always_on():
    jobs = _jobs()
    groups = [{"changes"}, set(_GATED), _GATES, set(_ALWAYS_ON)]
    assert sum(len(group) for group in groups) == len(set().union(*groups))
    assert set(jobs) == set().union(*groups)


def test_the_job_changes_has_an_output_for_each_scope_and_the_legs():
    job = _jobs()["changes"]
    assert "needs" not in job and "if" not in job
    assert set(job["outputs"]) == {*_SCOPES, "server-legs"}
    for name, value in job["outputs"].items():
        assert value == f"${{{{ steps.changes.outputs.{name} }}}}"
    (step,) = (step for step in job["steps"] if step.get("id") == "changes")
    assert step["run"] == 'python3 .github/scripts/ci_changes.py >> "$GITHUB_OUTPUT"'
    assert step["env"] == {
        "EVENT": "${{ github.event_name }}",
        "BASE_REF": "${{ github.base_ref }}",
        "SHA": "${{ github.sha }}",
    }
    # git diff origin/$BASE_REF...$SHA needs the base and the merge base.
    (checkout,) = (s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0


@pytest.mark.parametrize("name", sorted(_GATED))
def test_a_gated_job_runs_unless_its_output_is_false(name):
    job, output = _jobs()[name], _GATED[name]
    assert output in _SCOPES
    assert job["needs"] == "changes"
    assert job["if"] == f"${{{{ !cancelled() && needs.changes.outputs.{output} != 'false' }}}}"

    def runs(value: str, cancelled: bool = False) -> bool:
        needs = {"changes": {"outputs": {output: value}}}
        return bool(_evaluate(job["if"], cancelled=cancelled, needs=needs))

    assert runs("true")
    assert not runs("false")
    # The job changes failed and left its outputs empty: the suite runs.
    assert runs("")
    assert not runs("true", cancelled=True)


_NAMED = re.compile(r"apps/[\w./*-]+")
# The image lock jobs run the suite of their component against the lock its image installs; on
# a pull request only when the lock or the image changes (Kevin's trade-off, R-1340). The
# directory they work in is no part of their scope, the files they install from are.
_LOCK_JOBS = {"python-lock-server", "python-lock-monitoring", "python-lock-ca-issuer"}


@pytest.mark.parametrize("name", sorted(_GATED))
def test_what_a_gated_job_works_in_and_names_lies_in_its_scope(name):
    job, scope = _jobs()[name], _SCOPES[_GATED[name]]
    named = set()
    for step in job["steps"]:
        named |= set(_NAMED.findall(step.get("run", "") + json.dumps(step.get("with", {}))))
        if "working-directory" in step and name not in _LOCK_JOBS:
            named.add(f"{step['working-directory']}/**")
    assert named, name
    misses = [
        f"{pattern}: {hit}"
        for pattern in sorted(named)
        for hit in _files(pattern)
        if not ci_changes.matches(scope, hit)
    ]
    assert not misses, misses


@pytest.mark.parametrize("name", sorted(_ALWAYS_ON))
def test_a_job_that_always_runs_reads_no_output_of_changes(name):
    job = _jobs()[name]
    assert "changes" not in json.dumps(job.get("needs", "")), name
    assert "needs.changes" not in json.dumps(job), name


def test_every_file_under_apps_belongs_to_a_gated_suite_or_a_job_that_always_runs():
    always = tuple(pattern for patterns in _ALWAYS_ON.values() for pattern in patterns)
    files = [path for path in _tree() if path.startswith("apps/")]
    assert len(files) > 1000, len(files)
    orphans = [
        path
        for path in files
        if not ci_changes.matches(always, path)
        and not any(ci_changes.matches(scope, path) for scope in _SCOPES.values())
    ]
    assert not orphans, orphans


# --- what the suites read ------------------------------------------------------------------


def test_what_the_frps_image_takes_from_the_tree_is_in_the_server_scope():
    # Docker reads the file top-down, the last pattern that matches decides; the leading *
    # leaves nothing in, each ! takes a path in, a later line out again.
    lines = (_ROOT / "apps" / "frps" / "Dockerfile.dockerignore").read_text().splitlines()
    rules = [line for line in lines if line and not line.startswith("#")]
    assert rules[0] == "*"
    patterns = tuple(rule[1:] if rule.startswith("!") else f"!{rule}" for rule in rules[1:])
    context = [path for path in _tree() if ci_changes.matches(patterns, path)]
    assert "apps/frps/frps-supervisor.sh" in context
    assert "apps/agent/internal/frpspolicy/policy.go" in context
    assert not [path for path in context if path.endswith("_test.go")]
    outside = [path for path in context if not ci_changes.matches(_SCOPES["server"], path)]
    assert not outside, outside


_INCLUDE = re.compile(r'include_(?:str|bytes)!\("([^"]+)"\)')


def test_what_the_rust_sources_include_is_in_the_scope_of_rust_windows():
    tree = set(_tree())
    sources = [p for p in tree if p.startswith("apps/desktop/src-tauri/") and p.endswith(".rs")]
    included = {
        os.path.normpath(os.path.join(os.path.dirname(source), target))
        for source in sources
        for target in _INCLUDE.findall((_ROOT / source).read_text(encoding="utf-8"))
    }
    assert "apps/agent/internal/credentials/store.go" in included
    assert included <= tree, included - tree
    outside = [p for p in included if not ci_changes.matches(_SCOPES["rust-windows"], p)]
    assert not outside, outside


_AREAS = ("apps", "docs", "tasks", "changelog.d")
_TOKEN = re.compile(r"(?<![\w./-])((?:apps|docs|tasks|changelog\.d)/[^\s\"'`]*)")


def _render(node: ast.AST) -> str | None:
    """A string constant or an f-string, with * for each value it formats in."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "*" for v in node.values)
    return None


def _chain(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _chain(node.left) + _chain(node.right)
    return [node]


def _join(base: str | None, parts: list[ast.AST]) -> str | None:
    if base is None:
        return None
    texts = [base, *("*" if _render(part) is None else _render(part) for part in parts)]
    path = "/".join(text for text in texts if text)
    return posixpath.normpath(path) if path else ""


def _anchor(node: ast.AST, names: dict[str, str], here: str) -> str | None:
    """The path, relative to the root of the tree, of an expression built on __file__ (here,
    the source's own path): Path(), .resolve(), .parent, .parents[k], /, .joinpath(),
    .with_name() and os.path's abspath, dirname and join; a name bound to one counts as one."""
    if isinstance(node, ast.Name):
        return here if node.id == "__file__" else names.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _join(_anchor(node.left, names, here), [node.right])
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = _anchor(node.value, names, here)
        return None if base is None else posixpath.dirname(base)
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "parents"
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, int)
    ):
        base = _anchor(node.value.value, names, here)
        for _ in range(node.slice.value + 1):
            base = None if base is None else posixpath.dirname(base)
        return base
    if not isinstance(node, ast.Call):
        return None
    func, args = node.func, node.args
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name == "Path" and len(args) == 1:
        return _anchor(args[0], names, here)
    if not isinstance(func, ast.Attribute):
        return None
    if name in ("abspath", "realpath") and len(args) == 1:
        return _anchor(args[0], names, here)
    if name == "dirname" and len(args) == 1:
        base = _anchor(args[0], names, here)
        return None if base is None else posixpath.dirname(base)
    if name == "join" and args:
        return _join(_anchor(args[0], names, here), args[1:])
    base = _anchor(func.value, names, here)
    if name in ("resolve", "absolute") and not args:
        return base
    if name == "joinpath":
        return _join(base, args)
    if name == "with_name" and len(args) == 1 and base is not None:
        return _join(posixpath.dirname(base), args)
    return None


def _names(tree: ast.AST, here: str) -> dict[str, str]:
    """The names bound to an expression built on __file__, in the order ast.walk meets them
    (module level first); a name bound to two such paths stands for neither."""
    names: dict[str, str] = {}
    twice: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if not isinstance(target, ast.Name) or target.id in twice:
            continue
        path = _anchor(value, names, here)
        if path is None:
            continue
        if names.setdefault(target.id, path) != path:
            twice.add(target.id)
            del names[target.id]
    return names


def _paths(tree: ast.AST, here: str) -> set[str]:
    """The paths into the repository the Python source at here names, as patterns with * for
    each part computed at run time: the expressions built on __file__, the / chains and join
    calls whose first literal starts in an area of the tree, and the paths written in other
    strings. Docstrings and comments name no file."""
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and _render(body[0].value) is not None:
                skip.add(id(body[0].value))
    names = _names(tree, here)
    found: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        # A bare name is where a path is used, not where it is built.
        anchored = None if isinstance(node, ast.Name) else _anchor(node, names, here)
        if anchored is not None:
            skip.update(id(inner) for inner in ast.walk(node) if inner is not node)
            # _ROOT / path: the strings that path takes name themselves.
            if "*" not in anchored.split("/")[0]:
                found.add(anchored)
            continue
        parts = None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            parts = _chain(node)
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", "") in ("join", "joinpath"):
            parts = list(node.args)
        if parts is not None:
            # ast.walk goes outside in: the inner links of a chain are part of this one.
            skip.update(id(inner) for part in parts for inner in ast.walk(part))
            skip.update(id(inner) for inner in ast.walk(node) if inner is not node)
            texts = [_render(part) for part in parts]
            starts = [i for i, text in enumerate(texts) if text and text.split("/")[0] in _AREAS]
            if starts:
                path = "/".join("*" if text is None else text for text in texts[starts[0] :])
                found.add(re.sub("/+", "/", path))
            continue
        text = _render(node)
        if text is None:
            continue
        skip.update(id(inner) for inner in ast.walk(node) if inner is not node)
        for token in _TOKEN.findall(text):
            found.add(token.replace("\\.", ".").rstrip(".),:;"))
    return {path.rstrip("/") for path in found if path.rstrip("/") not in ("", *_AREAS)}


def _files(pattern: str) -> list[str]:
    parts = re.split(r"(\*\*|\*)", pattern)
    table = {"**": ".*", "*": "[^/]*"}
    regex = re.compile("".join(table.get(p, re.escape(p)) for p in parts) + "(/.*)?")
    return [path for path in _tree() if regex.fullmatch(path)]


# Suite -> the scope its files read from; the schemathesis job runs these files of each suite too.
_SUITES = {
    "apps/server/tests": "server",
    "apps/monitoring/tests": "monitoring",
    "apps/ca-issuer/tests": "ca-issuer",
}
_SCHEMATHESIS = {"test_schemathesis.py", "conftest.py"}
# The paths these files name as data, not as files they read.
_DATA = {"apps/server/tests/test_ci_changes.py"}
# (test file, path it names) -> why that is no file outside the scope of its suite it reads
_NOT_READ = {
    (
        "apps/server/tests/test_frps_policy_image.py",
        "apps/agent",
    ): "the base of what it reads, the Go sources the frps image takes, which lie in the server "
    "scope (test_what_the_frps_image_takes_from_the_tree_is_in_the_server_scope)",
    (
        "apps/server/tests/test_frps_policy_image.py",
        "apps/agent/*",
    ): "the Go packages of the frps-policy plugin under it (_PLUGIN_SOURCES), which lie in the "
    "server scope",
    (
        "apps/server/tests/test_ssrf_parity.py",
        "apps/monitoring",
    ): "the label of a diff; the file it reads is apps/monitoring/app/core/ssrf.py",
}


def _references() -> list[tuple[str, str, str]]:
    """(test file, path pattern, scope) for every path the three Python suites name."""
    found = []
    for directory, scope in _SUITES.items():
        sources = [p for p in _tree() if p.startswith(f"{directory}/") and p.endswith(".py")]
        for source in (p for p in sources if p not in _DATA):
            tree = ast.parse((_ROOT / source).read_text(encoding="utf-8"), filename=source)
            scopes = [scope] + (
                ["schemathesis"] if source.rsplit("/", 1)[1] in _SCHEMATHESIS else []
            )
            for path in sorted(_paths(tree, source)):
                found += [(source, path, name) for name in scopes]
    return found


def test_the_scan_finds_the_paths_the_suites_read_outside_their_component():
    pairs = {(source, path) for source, path, _ in _references()}
    for pair in [
        (
            "apps/monitoring/tests/test_alerter_hub.py",
            "apps/server/app/modules/notifications/schemas.py",
        ),
        ("apps/server/tests/test_frp_tunnel_access.py", "apps/desktop/src-tauri/src/tunnel.rs"),
        ("apps/server/tests/test_env_parity.py", "apps/monitoring/app/core/config.py"),
        ("apps/server/tests/test_hook_examples.py", "docs/examples"),
        (
            "apps/server/tests/test_config_generator.py",
            "apps/agent/internal/frpc/testdata/server_frpc.toml",
        ),
        ("apps/server/tests/test_frps_supervisor.py", "apps/frps"),
    ]:
        assert pair in pairs, pair


def test_the_scan_reads_chains_f_strings_and_strings_but_no_docstrings():
    source = '''
"""Reads docs/admin/users.html, says the docstring."""
A = _ROOT / "apps" / name / "app"
B = _ROOT / "apps/web/src/lib" / "x.ts"
C = f"apps/{name}/Dockerfile"
D = os.path.join(_ROOT, "docs", "examples")
E = "see apps/frps/frps-supervisor\\\\.sh)."


def f():
    """And apps/desktop/ui/src/App.svelte here."""
'''
    assert _paths(ast.parse(source), "apps/server/tests/test_x.py") == {
        "apps/*/app",
        "apps/web/src/lib/x.ts",
        "apps/*/Dockerfile",
        "docs/examples",
        "apps/frps/frps-supervisor.sh",
    }


def test_the_scan_follows_the_paths_built_on_the_file_itself():
    source = """
ROOT = Path(__file__).resolve().parents[3]
FIXTURE = (
    Path(__file__).resolve().parents[2] / "agent" / "internal" / "frpc" / "server_frpc.toml"
)
FRPS_DIR = Path(__file__).parents[2] / "frps"
SCRIPT = FRPS_DIR / "frps-supervisor.sh"
APP = Path(__file__).resolve().parent.parent / "app"
MARKER = Path(__file__).with_name("marker")
CWD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(os.path.dirname(__file__), "data", name)
WEB = Path(__file__).resolve().parents[3].joinpath("apps", "web")
OTHER = Path(cli.__file__).parent / "x"


def f():
    compose = ROOT / ".github" / "workflows"
    shadow = Path(__file__).parent
    shadow = Path(__file__).parents[1]
    return shadow / "lost"
"""
    assert _paths(ast.parse(source), "apps/server/tests/test_x.py") == {
        "apps/agent/internal/frpc/server_frpc.toml",
        "apps/frps",
        "apps/frps/frps-supervisor.sh",
        "apps/server/app",
        "apps/server/tests/marker",
        "apps/server",
        "apps/server/tests/data/*",
        "apps/web",
        ".github/workflows",
        "apps/server/tests",
    }


def test_every_path_a_python_suite_names_lies_in_the_scope_of_its_suite():
    misses = []
    for source, path, scope in _references():
        if (source, path) in _NOT_READ:
            continue
        for hit in _files(path):
            # A change outside the narrow areas runs every suite anyway.
            if ci_changes.matches(ci_changes.NARROW, hit) and not ci_changes.matches(
                _SCOPES[scope], hit
            ):
                misses.append(f"{source} names {path}: {hit} is not in the scope {scope}")
    assert not misses, "\n".join(misses)


def test_the_exceptions_are_still_named():
    pairs = {(source, path) for source, path, _ in _references()}
    assert set(_NOT_READ) <= pairs, set(_NOT_READ) - pairs


# --- the script against a repository --------------------------------------------------------


@pytest.fixture
def pr_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "apps" / "agent").mkdir(parents=True)
    (repo / "apps" / "agent" / "main.go").write_text("package main\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (repo / "docs").mkdir()
    _git(repo, "mv", "apps/agent/main.go", "docs/main.go")
    _git(repo, "commit", "-q", "-m", "the pull request")
    return repo


def _env(**env: str) -> dict:
    return {
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
    } | env


def test_a_rename_counts_its_old_and_its_new_path(pr_repo, monkeypatch):
    monkeypatch.chdir(pr_repo)
    for name, value in _env().items():
        monkeypatch.setenv(name, value)
    sha = _git(pr_repo, "rev-parse", "HEAD")
    assert ci_changes.changed_paths("main", sha) == ["apps/agent/main.go", "docs/main.go"]


def _run(cwd: Path, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT)],
        cwd=cwd,
        env=_env(**env),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_script_prints_one_line_for_each_output(pr_repo):
    sha = _git(pr_repo, "rev-parse", "HEAD")
    run = _run(pr_repo, EVENT="pull_request", BASE_REF="main", SHA=sha)
    assert run.returncode == 0, run.stderr
    want = {**_on("agent-windows"), "server-legs": '["3.14"]'}
    assert run.stdout.splitlines() == [f"{name}={value}" for name, value in want.items()]
    assert "2 changed paths" in run.stderr
    assert "agent-windows: apps/agent/main.go" in run.stderr


def test_the_script_reads_no_paths_outside_a_pull_request(tmp_path):
    run = _run(tmp_path, EVENT="push", BASE_REF="", SHA="0" * 40)
    assert run.returncode == 0, run.stderr
    want = {**_ALL, "server-legs": '["3.14","3.15"]'}
    assert run.stdout.splitlines() == [f"{name}={value}" for name, value in want.items()]


def test_the_script_fails_without_output_when_git_cannot_name_the_paths(pr_repo):
    # The job changes fails, its outputs stay empty, and every gated job runs.
    sha = _git(pr_repo, "rev-parse", "HEAD")
    run = _run(pr_repo, EVENT="pull_request", BASE_REF="gone", SHA=sha)
    assert run.returncode != 0
    assert run.stdout == ""
