# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Environment parity: compose <-> .env.example <-> config.py (harness 8a, T6).

Three separately maintained descriptions of the same configuration surface, and
nothing compared them. Each drift has its own way of being invisible:

  (a) a variable a service reads with no default, that compose never sets, is an
      empty string at runtime — a misconfiguration that looks like a valid value.
  (b) a key compose hands a service that the service does not read is either a
      leftover or a rename that landed on one side only. DOMAIN, EXTRA_SANS and
      PGPASSWORD were all sitting on services that never read them.
  (c) a `${VAR}` in compose that .env.example does not document is a knob nobody
      can find; a key documented in .env.example that compose never substitutes
      is worse — DB_POOL_SIZE and DB_MAX_OVERFLOW came with instructions for
      tuning them, and setting them changed nothing.

No exception list. Where a rule needed an exception, the rule was wrong instead:
"reads without a default" is a property of the FILE, not of the occurrence —
monitoring/config.py reads SMTP_PORT with a default and mentions it again without
one in a warning message, and that is not a missing default.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE = _ROOT / "docker-compose.yml"
_ENV_EXAMPLE = _ROOT / ".env.example"

# Compose services that run our Python images, and the component each one runs.
# Two services share the server image; every key has to hold for both.
_PYTHON_SERVICES = {
    "server": "server",
    "scheduler": "server",
    "monitoring": "monitoring",
    "ca-issuer": "ca-issuer",
}
_CONFIG_MODULE = {
    "server": "apps/server/app/core/config.py",
    "monitoring": "apps/monitoring/app/core/config.py",
    "ca-issuer": "apps/ca-issuer/app/config.py",
}

# Interpreter and OS variables. The container sets them for Python and for libc,
# no application code reads them, and requiring it would be wrong — a category
# rule, not an exception list. Of the four patterns only TZ matches anything in
# compose today; the rest are there so the rule stays a rule when one appears.
_RUNTIME_VARIABLE = re.compile(r"^(PYTHON\w*|TZ|LANG|LC_\w+)$")

_ENV_READ = re.compile(r'os\.environ(?:\.get)?\(?\[?\s*["\']([A-Z][A-Z0-9_]*)["\']')
_ENV_READ_WITH_DEFAULT = re.compile(r'os\.environ\.get\(\s*["\']([A-Z][A-Z0-9_]*)["\']\s*,')
_SUBSTITUTION = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")
# An .env.example key, whether active or commented out — a commented example is
# still the place an operator looks the name up.
_EXAMPLE_KEY = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _compose_environment() -> dict[str, set[str]]:
    """The `environment:` keys per service.

    Hand-parsed rather than via PyYAML: the shape needed here is a flat list of
    `- KEY=value` entries under a service key, and a regex keeps the test honest
    about what it reads. A wholesale rewrite (mapping form, a trailing comment on
    the service header) is loud — the parse then yields zero keys and the
    non-empty guard below fails — while a single reworded entry is not, which is
    why the entry pattern accepts quoting and any indentation.
    """
    out: dict[str, set[str]] = {}
    service, in_env = None, False
    for line in _COMPOSE.read_text(encoding="utf-8").splitlines():
        header = re.match(r"^  ([A-Za-z][\w-]*):\s*$", line)
        if header:
            service, in_env = header.group(1), False
            out.setdefault(service, set())
            continue
        if re.match(r"^    environment:\s*$", line):
            in_env = True
            continue
        if re.match(r"^    \S", line):
            in_env = False
            continue
        if in_env and service:
            # `- "KEY=x"` und abweichende Einrueckung sind YAML-legal und in
            # Compose-Dateien ueblich. Eine Regex, die nur die eine Schreibweise
            # kennt, verschluckt einen umgeschriebenen Eintrag spurlos — genau
            # die Klasse Fund, fuer die Regel (b) existiert.
            entry = re.match(r'^\s+-\s*"?([A-Z][A-Z0-9_]*)=', line)
            if entry:
                out[service].add(entry.group(1))
    return out


def _read_by(component: str) -> set[str]:
    """Every variable the component's code or entrypoint reads."""
    names: set[str] = set()
    app = _ROOT / "apps" / component / "app"
    for py in app.rglob("*.py"):
        names.update(_ENV_READ.findall(py.read_text(encoding="utf-8", errors="replace")))
    entrypoint = _ROOT / "apps" / component / "docker-entrypoint.sh"
    if entrypoint.exists():
        text = entrypoint.read_text(encoding="utf-8")
        names.update(re.findall(r"\$\{?([A-Z][A-Z0-9_]*)", text))
    return names


def _read_without_default(component: str) -> set[str]:
    text = (_ROOT / _CONFIG_MODULE[component]).read_text(encoding="utf-8")
    return set(_ENV_READ.findall(text)) - set(_ENV_READ_WITH_DEFAULT.findall(text))


def test_the_scan_reads_all_three_sides():
    """Non-empty guard: any of the three parsers coming back empty would make
    every comparison below vacuously true."""
    compose = _compose_environment()
    assert len(compose) >= 5, f"only {len(compose)} compose services parsed"
    assert set(_PYTHON_SERVICES) <= set(compose), (
        f"compose no longer has: {sorted(set(_PYTHON_SERVICES) - set(compose))}"
    )
    # Ten per SIDE, as the ledger asks; per service only five, because the
    # ca-issuer legitimately takes nine — an emptied service block is still
    # caught, an honestly small one is not called a broken parse.
    for service in _PYTHON_SERVICES:
        assert len(compose[service]) >= 5, f"{service}: only {len(compose[service])} keys"
    all_keys = set().union(*(compose[s] for s in _PYTHON_SERVICES))
    assert len(all_keys) >= 10, f"only {len(all_keys)} distinct compose keys"
    assert len(_SUBSTITUTION.findall(_COMPOSE.read_text(encoding="utf-8"))) >= 10
    assert len(set(_EXAMPLE_KEY.findall(_ENV_EXAMPLE.read_text(encoding="utf-8")))) >= 10
    for component in _CONFIG_MODULE:
        assert len(_read_by(component)) >= 10, f"{component}: too few reads found"


def test_every_variable_without_a_default_is_set_in_compose():
    """Narrow by nature: almost every read carries a default, so the set this
    compares is small (one variable today). A green here means "no new read
    without a default slipped in", not broad coverage."""
    compose = _compose_environment()
    missing: dict[str, list[str]] = {}
    for service, component in _PYTHON_SERVICES.items():
        absent = sorted(_read_without_default(component) - compose[service])
        if absent:
            missing[service] = absent
    assert missing == {}, (
        f"read without a default and not set in compose — these arrive as an empty "
        f"string, which reads like a valid value: {missing}"
    )


def test_compose_gives_no_service_a_key_it_does_not_read():
    compose = _compose_environment()
    unread: dict[str, list[str]] = {}
    for service, component in _PYTHON_SERVICES.items():
        known = _read_by(component)
        stale = sorted(
            key for key in compose[service] if not _RUNTIME_VARIABLE.match(key) and key not in known
        )
        if stale:
            unread[service] = stale
    assert unread == {}, (
        f"compose sets keys the service never reads — a leftover, or a rename that "
        f"landed on one side only: {unread}"
    )


def _substituted_and_documented() -> tuple[set[str], set[str]]:
    return (
        set(_SUBSTITUTION.findall(_COMPOSE.read_text(encoding="utf-8"))),
        set(_EXAMPLE_KEY.findall(_ENV_EXAMPLE.read_text(encoding="utf-8"))),
    )


# Two tests, not two assertions in one: the first failing one would otherwise
# hide the second list, and the two drifts are usually introduced together.
def test_every_substituted_knob_is_documented():
    substituted, documented = _substituted_and_documented()
    undocumented = sorted(substituted - documented)
    assert undocumented == [], (
        f"compose substitutes knobs .env.example never mentions — nobody can find "
        f"them: {undocumented}"
    )


def test_every_documented_knob_reaches_a_service():
    substituted, documented = _substituted_and_documented()
    ineffective = sorted(documented - substituted)
    assert ineffective == [], (
        f".env.example documents knobs compose never passes on — setting them changes "
        f"nothing: {ineffective}"
    )


def test_both_services_of_the_server_image_share_the_pool_knobs():
    """(c) compares the whole file, so removing a knob from ONE of the two
    services that run the server image stays green — and the documented
    arithmetic (WEB_CONCURRENCY x (pool + overflow)) would then be wrong for the
    scheduler, which holds its own engine."""
    compose = _compose_environment()
    for knob in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW"):
        carriers = sorted(svc for svc in ("server", "scheduler") if knob in compose[svc])
        assert carriers == ["scheduler", "server"], (
            f"{knob} reaches only {carriers} — both services run the server image and "
            f"each opens its own pool"
        )
