# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The images of server and scheduler (Dockerfile), ca-issuer and monitoring end their last stage
with the same step: every program in the bin directories and below /usr/lib/postgresql (the
PostgreSQL clients), an ELF file with an x bit, is for anyone but root, its owner, to execute
only; scripts and symlinks stay as they are, and a directory of the list the image lacks is
skipped. A process of app that gosu starts from such a program is not dumpable, so the entries
in /proc/<pid> are root's. Scripts stay readable: only the program that runs counts, for a
script its interpreter.

One test reads the Dockerfiles. The tests on a container run the step, as read from them, in a
container of the base image all three pin, with the default capabilities, and start processes
under the UID of app the way gosu does: the UID changes before the exec, so the program starts
without the capabilities of the container. docker exec -u keeps them, and a program it starts
stays dumpable even when its user cannot read it. They skip when Docker or the pinned base
image is not at hand.

The PostgreSQL clients cannot read their own program: pg_isready warns on stderr and runs on,
psql stops. So no entrypoint runs psql, and monitoring creates its database through psycopg;
the last test runs that program of its entrypoint against the test database."""

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

_ROOT = Path(__file__).resolve().parents[3]
_DOCKERFILES = ("Dockerfile", "apps/ca-issuer/Dockerfile", "apps/monitoring/Dockerfile")
_BIN_DIRS = ("/usr/local/bin", "/usr/local/sbin", "/usr/bin", "/usr/sbin")
# Where the PostgreSQL client programs lie, in <version>/bin below it: in the images of server
# and monitoring, not in that of ca-issuer nor in the base image.
_PG_DIR = "/usr/lib/postgresql"
_ENTRYPOINTS = (
    "apps/server/docker-entrypoint.sh",
    "apps/ca-issuer/docker-entrypoint.sh",
    "apps/monitoring/docker-entrypoint.sh",
)
# The GID `groupadd -r app` gives app on the base image: its first system GID.
_APP_GID = 999
_WAIT = 20

# Starts sys.argv[3:] under the UID sys.argv[1] and the GID sys.argv[2], as gosu does.
_STARTER = """import os, sys
os.setgroups([])
os.setgid(int(sys.argv[2]))
os.setuid(int(sys.argv[1]))
os.execvp(sys.argv[3], sys.argv[3:])
"""
# Every regular file with an x bit below the directories in sys.argv[1:], one JSON line each:
# path, mode, owner and whether it is an ELF file.
_PROGRAMS = """import json, os, stat, sys
for top in sys.argv[1:]:
    for directory, _, names in os.walk(top):
        for name in names:
            path = os.path.join(directory, name)
            st = os.lstat(path)
            if stat.S_ISREG(st.st_mode) and st.st_mode & 0o111:
                with open(path, "rb") as program:
                    elf = program.read(4) == b"\\x7fELF"
                print(json.dumps([path, stat.S_IMODE(st.st_mode), st.st_uid, elf]))
"""
# Every process, one JSON line each: its real UID, the owner of /proc/<pid>/status and its
# command line.
_PROCESSES = """import json, os
for pid in filter(str.isdigit, os.listdir("/proc")):
    try:
        owner = os.stat(f"/proc/{pid}/status")
        with open(f"/proc/{pid}/status") as status:
            uid = next(line.split()[1] for line in status if line.startswith("Uid:"))
        with open(f"/proc/{pid}/cmdline", "rb") as cmdline:
            args = cmdline.read().decode().split("\\0")[:-1]
    except (FileNotFoundError, ProcessLookupError):
        continue
    print(json.dumps([int(uid), f"{owner.st_uid}:{owner.st_gid}", args]))
"""


def _instructions(path: str) -> list[str]:
    """The instructions of the Dockerfile at path, each as written, its continuation lines
    included; comments and blank lines left out, as Docker leaves them out."""
    instructions, current = [], []
    for line in (_ROOT / path).read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#") or (not current and not line.strip()):
            continue
        current.append(line)
        if not line.endswith("\\"):
            instructions.append("\n".join(current))
            current = []
    assert not current, f"{path}: ends in a continuation line"
    return instructions


def _keyword(instruction: str) -> str:
    return instruction.split(None, 1)[0].upper()


def _last_stage(path: str) -> list[str]:
    """The instructions of the last stage, from its FROM on."""
    instructions = _instructions(path)
    froms = [i for i, instruction in enumerate(instructions) if _keyword(instruction) == "FROM"]
    assert froms, path
    return instructions[froms[-1] :]


def _step(path: str) -> str:
    """The last RUN of the last stage, as written."""
    runs = [instruction for instruction in _last_stage(path) if _keyword(instruction) == "RUN"]
    assert runs, path
    return runs[-1]


def _command(run: str) -> str:
    """The shell command of a RUN in shell form, its lines joined as Docker joins them."""
    lines = run.split("\n")
    joined = "".join(line[:-1] if line.endswith("\\") else line for line in lines)
    keyword, command = joined.split(None, 1)
    assert keyword == "RUN" and not command.startswith("["), run
    return command


def _app_uid() -> int:
    """The UID of app, the same in all three images."""
    uids = set()
    for path in _DOCKERFILES:
        found = re.findall(r"\buseradd\b.* -u (\d+) .*\bapp\b", (_ROOT / path).read_text())
        assert len(found) == 1, path
        uids.add(int(found[0]))
    assert len(uids) == 1, uids
    return uids.pop()


def _base() -> str:
    """The base image of the last stage, the same pinned image in all three."""
    bases = {re.match(r"FROM (\S+)", _last_stage(path)[0])[1] for path in _DOCKERFILES}
    assert len(bases) == 1, bases
    (base,) = bases
    assert re.search(r"@sha256:[0-9a-f]{64}$", base), base
    return base


def test_each_image_ends_its_last_stage_with_the_same_step_that_leaves_its_programs_execute_only():
    for path in _DOCKERFILES:
        stage = _last_stage(path)
        runs = [i for i, instruction in enumerate(stage) if _keyword(instruction) == "RUN"]
        # The step comes after every RUN that installs programs, and nothing comes into the
        # image after it.
        install = re.compile(r"\b(apt-get|pip) install\b")
        installs = [(i, found[1]) for i in runs if (found := install.search(stage[i]))]
        assert {kind for _, kind in installs} == {"apt-get", "pip"}, (path, stage)
        assert installs[-1][0] < runs[-1], (path, stage)
        after = {_keyword(instruction) for instruction in stage[runs[-1] + 1 :]}
        assert not after & {"RUN", "COPY", "ADD"}, (path, after)
    steps = {path: _step(path) for path in _DOCKERFILES}
    step = steps[_DOCKERFILES[0]]
    assert set(steps.values()) == {step}, steps
    words = re.split(r"[\s;]+", step)
    assert all(directory in words for directory in (*_BIN_DIRS, _PG_DIR)), step
    assert "chmod go-r" in step, step


class Box:
    """A container of the base image, as root with the default capabilities."""

    def __init__(self, docker: str, name: str):
        self.docker, self.name = docker, name
        self.before: dict[str, tuple[int, int, bool]] = {}

    def exec(self, *args: str, detach: bool = False, stdin: str | None = None):
        run = [self.docker, "exec", *(["-d"] if detach else []), *(["-i"] if stdin else [])]
        return subprocess.run([*run, self.name, *args], input=stdin, capture_output=True, text=True)

    def as_app(self, *command: str, detach: bool = False):
        """Runs command under the UID and GID of app through the starter."""
        uid, gid = str(_app_uid()), str(_APP_GID)
        return self.exec("python3", "-c", _STARTER, uid, gid, *command, detach=detach)

    def programs(self) -> dict[str, tuple[int, int, bool]]:
        """Mode, owner and whether it is an ELF file of every file with an x bit in the bin
        directories."""
        result = self.exec("python3", "-c", _PROGRAMS, *_BIN_DIRS)
        assert result.returncode == 0, result.stderr
        entries = [json.loads(line) for line in result.stdout.splitlines()]
        return {path: (mode, uid, elf) for path, mode, uid, elf in entries}

    def processes(self, uid: int) -> dict[tuple[str, ...], str]:
        """Owner of /proc/<pid>/status by command line, for every process of uid."""
        result = self.exec("python3", "-c", _PROCESSES)
        assert result.returncode == 0, result.stderr
        entries = [json.loads(line) for line in result.stdout.splitlines()]
        return {tuple(args): owner for real, owner, args in entries if real == uid}


@pytest.fixture(scope="module")
def box():
    """A container of the base image after the step, with the files of the bin directories as
    they were before it (box.before)."""
    base = _base()
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not available")
    if subprocess.run([docker, "image", "inspect", base], capture_output=True).returncode != 0:
        pytest.skip(f"no docker daemon or {base} not present locally")
    name = f"images-exec-only-test-{uuid.uuid4().hex[:12]}"
    run = [docker, "run", "-d", "--name", name, "--network", "none", base, "sleep", "infinity"]
    subprocess.run(run, check=True, capture_output=True)
    try:
        box = Box(docker, name)
        box.before = box.programs()
        # Before the step, others read the programs: the checks below can fail.
        assert any(elf and mode & 0o044 for mode, _, elf in box.before.values()), box.before
        # The base image has no PostgreSQL clients, as the image of ca-issuer has none: the
        # step meets a directory of its list that is not there and runs on without an error.
        assert box.exec("test", "-e", _PG_DIR).returncode == 1
        result = box.exec("sh", "-c", _command(_step(_DOCKERFILES[0])))
        assert result.returncode == 0 and not result.stderr, result.stderr
        yield box
    finally:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)


def test_after_the_step_the_programs_of_the_bin_directories_are_for_others_to_execute_only(box):
    # Every ELF file loses read for group and others, and nothing else changes: not its owner
    # (root), not a setuid bit, not a script.
    after = box.programs()
    expected = {
        path: (mode & ~0o044 if elf else mode, uid, elf)
        for path, (mode, uid, elf) in box.before.items()
    }
    assert after == expected
    assert {uid for _, uid, elf in after.values() if elf} == {0}
    assert sum(elf for _, _, elf in after.values()) > 100, after
    assert box.exec("stat", "-c", "%a", "/usr/local/bin/pip3").stdout == "755\n"


def test_the_step_takes_in_the_postgresql_clients_where_the_image_has_them(box):
    # Laid out as postgresql-client lays them out: an ELF program and a script, both 0755,
    # in /usr/lib/postgresql/<version>/bin. The step runs again; in the bin directories it has
    # nothing left to change.
    program, script = f"{_PG_DIR}/17/bin/pg_isready", f"{_PG_DIR}/17/bin/pg_script"
    lay_out = (
        f"mkdir -p {_PG_DIR}/17/bin && cp /usr/bin/sleep {program}"
        f" && printf '#!/bin/sh\\n' > {script} && chmod 0755 {program} {script}"
    )
    assert box.exec("sh", "-c", lay_out).returncode == 0
    assert box.exec("stat", "-c", "%a", program, script).stdout == "755\n755\n"
    result = box.exec("sh", "-c", _command(_step(_DOCKERFILES[0])))
    assert result.returncode == 0 and not result.stderr, result.stderr
    assert box.exec("stat", "-c", "%a %U", program, script).stdout == "711 root\n755 root\n"


def test_after_the_step_a_process_of_app_is_not_dumpable(box):
    uid = _app_uid()
    script = "#!/usr/local/bin/python3.12\nimport time\ntime.sleep(602)\n"
    write = "cat > /tmp/sleeper.py && chmod 0755 /tmp/sleeper.py"
    assert box.exec("sh", "-c", write, stdin=script).returncode == 0
    # A copy of sleep anyone reads: the counter-check, a process of app that stays dumpable.
    copy = "cp /usr/bin/sleep /tmp/sleep && chmod 0755 /tmp/sleep"
    assert box.exec("sh", "-c", copy).returncode == 0
    commands = [
        ("python3", "-c", "import time; time.sleep(600)"),
        # The `:` keeps dash from replacing itself with sleep: both run.
        ("sh", "-c", "sleep 601; :"),
        ("/tmp/sleeper.py",),
        ("/tmp/sleep", "603"),
    ]
    for command in commands:
        assert box.as_app(*command, detach=True).returncode == 0, command
    expected = {
        ("python3", "-c", "import time; time.sleep(600)"): "0:0",
        ("sh", "-c", "sleep 601; :"): "0:0",
        ("sleep", "601"): "0:0",
        ("/usr/local/bin/python3.12", "/tmp/sleeper.py"): "0:0",
        ("/tmp/sleep", "603"): f"{uid}:{_APP_GID}",
    }
    deadline = time.monotonic() + _WAIT
    while (found := box.processes(uid)).keys() != expected.keys():
        assert time.monotonic() < deadline, found
        time.sleep(0.2)
    assert found == expected


def test_after_the_step_pip_runs_as_app(box):
    result = box.as_app("pip3", "--version")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("pip "), result.stdout


def test_no_entrypoint_runs_psql():
    for path in _ENTRYPOINTS:
        lines = (_ROOT / path).read_text(encoding="utf-8").splitlines()
        code = [line for line in lines if not line.lstrip().startswith("#")]
        assert not [line for line in code if re.search(r"\bpsql\b", line)], path


def _database_program() -> str:
    """The Python program with which the entrypoint of monitoring creates its database."""
    path = _ENTRYPOINTS[2]
    found = re.findall(
        r"python - <<'PY'\n(.*?\n)PY\n", (_ROOT / path).read_text(encoding="utf-8"), re.S
    )
    assert len(found) == 1, path
    return found[0]


def test_the_entrypoint_of_monitoring_creates_its_database_once(pg_engine):
    url = pg_engine.url
    # Quoted as an identifier, or the hyphens fail and the capital M is folded.
    name = f"ah-test-Monitor-{uuid.uuid4().hex[:12]}"
    env = {
        **os.environ,
        "PGHOST": url.host,
        "PGPORT": str(url.port or 5432),
        "PGUSER": url.username,
        "PGPASSWORD": url.password or "",
        "ADMIN_DB": url.database,
        "MONITOR_DB": name,
    }

    def run(**changed: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-"],
            input=_database_program(),
            env={**env, **changed},
            capture_output=True,
            text=True,
        )

    def exists() -> bool:
        with pg_engine.connect() as conn:
            query = text("SELECT count(*) FROM pg_database WHERE datname = :name")
            return conn.execute(query, {"name": name}).scalar() == 1

    try:
        assert not exists()
        first = run()
        assert (first.returncode, first.stderr) == (0, ""), first.stderr
        assert first.stdout == f"[entrypoint] Creating database {name}...\n"
        assert exists()
        again = run()
        assert (again.returncode, again.stdout, again.stderr) == (0, "", ""), again.stderr
        # A database it cannot reach ends the entrypoint, with a line that names no password.
        # The probe is a password of its own, not that of the test database: one like `test`
        # (testcontainers) stands in the database name the line names. Checked first and
        # without the values, so a failure prints no password either.
        sentinel = secrets.token_hex(16)
        failed = run(ADMIN_DB=f"{name}-missing", PGPASSWORD=sentinel)
        leaked = sentinel in failed.stdout + failed.stderr
        assert not leaked, "the output of the failed run names the password"
        assert failed.returncode == 1, failed.stderr
        assert failed.stderr.startswith(f"[entrypoint] ERROR: database {name}: "), failed.stderr
    finally:
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
