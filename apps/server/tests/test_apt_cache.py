# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The apt archive cache of the CI jobs (R-1602): .github/scripts/apt_cache.sh.

The key follows the package set, so a run whose archives all came from the cache is an exact
hit; a download that fails leaves what it fetched for the cache, and a failed attempt reads the
index again before the next one. sudo and apt-get are stand-ins on PATH that log their calls.
"""

import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / ".github" / "scripts" / "apt_cache.sh"

_APT_GET = """#!/usr/bin/env bash
echo "$*" >> "$STUB_LOG"
case " $* " in
*" --print-uris "*) cat "$STUB_URIS" ;;
*" --download-only "*)
    n=$(( $(cat "$STUB_COUNT" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "$STUB_COUNT"
    [ "$n" -gt "${STUB_FAIL:-0}" ] || exit 100
    ;;
esac
exit 0
"""

_URIS = (
    "'http://archive.ubuntu.com/ubuntu/pool/main/g/gtk/libgtk-3-0_3.24_amd64.deb' "
    "libgtk-3-0_3.24_amd64.deb 3100000 SHA256:aaaa\n"
    "'http://archive.ubuntu.com/ubuntu/pool/main/p/patchelf/patchelf_0.18_amd64.deb' "
    "patchelf_0.18_amd64.deb 99000 SHA256:bbbb\n"
)


@pytest.fixture
def stub(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (bin_dir / "apt-get").write_text(_APT_GET)
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STUB_LOG": str(tmp_path / "log"),
        "STUB_URIS": str(tmp_path / "uris"),
        "STUB_COUNT": str(tmp_path / "count"),
        "APT_CACHE_SECONDS": "20",
        "RETRY_PAUSE": "0",
    }
    (tmp_path / "uris").write_text(_URIS)

    def run(*args, fail=0):
        (tmp_path / "log").write_text("")
        (tmp_path / "count").unlink(missing_ok=True)
        proc = subprocess.run(
            ["bash", str(_SCRIPT), *args],
            env={**env, "STUB_FAIL": str(fail)},
            capture_output=True,
            text=True,
            check=False,
        )
        calls = (tmp_path / "log").read_text().splitlines()
        return proc, calls

    run.uris = tmp_path / "uris"
    run.dir = tmp_path / "archives"
    return run


def _key(stub, prefix="apt-x-v3"):
    proc, calls = stub("key", str(stub.dir), prefix, "libgtk-3-dev", "patchelf")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip(), calls


def test_the_key_reads_the_index_first_and_hashes_the_archive_list(stub):
    key, calls = _key(stub)
    assert key.startswith("apt-x-v3-") and len(key) == len("apt-x-v3-") + 16
    assert len(calls) == 2
    assert calls[0].endswith("update -qq")
    assert "--print-uris" in calls[1] and calls[1].endswith("libgtk-3-dev patchelf")
    assert f"Dir::Cache::Archives={stub.dir}" in calls[1]


def test_the_key_stays_with_the_same_archives_and_moves_with_one_changed(stub):
    key, _ = _key(stub)
    lines = _URIS.splitlines()
    stub.uris.write_text("Reading package lists...\n" + "\n".join(reversed(lines)) + "\n")
    assert _key(stub)[0] == key
    stub.uris.write_text(_URIS.replace("99000", "99001"))
    assert _key(stub)[0] != key


def test_the_key_of_an_empty_list_is_a_key(stub):
    stub.uris.write_text("")
    key, _ = _key(stub)
    assert key.startswith("apt-x-v3-")


def test_install_downloads_then_installs_from_the_archives(stub):
    proc, calls = stub("install", str(stub.dir), "gnome-keyring")
    assert proc.returncode == 0, proc.stderr
    assert len(calls) == 3
    assert "--download-only" in calls[0]
    assert "--download-only" not in calls[1] and calls[1].endswith("gnome-keyring")
    assert calls[2].endswith("autoclean")
    assert all(f"Dir::Cache::Archives={stub.dir}" in c for c in calls)
    assert (stub.dir / "partial").is_dir()


def test_a_failed_download_reads_the_index_again_before_the_next_attempt(stub):
    proc, calls = stub("install", str(stub.dir), "gnome-keyring", fail=1)
    assert proc.returncode == 0, proc.stderr
    kinds = [
        "download" if "--download-only" in c else "update" if c.endswith("update -qq") else c
        for c in calls
    ]
    assert kinds[:3] == ["download", "update", "download"]
    assert len(calls) == 5
    assert "download attempt 1/3 ended with 100" in proc.stderr


def test_three_failed_downloads_fail_without_installing(stub):
    proc, calls = stub("install", str(stub.dir), "gnome-keyring", fail=9)
    assert proc.returncode == 100
    downloads = [c for c in calls if "--download-only" in c]
    updates = [c for c in calls if c.endswith("update -qq")]
    assert len(downloads) == 3
    # No index read after the last attempt: nothing would use it.
    assert len(updates) == 2
    assert len(calls) == 5


@pytest.mark.parametrize("args", [[], ["install", "/x"], ["key", "/x", "p"], ["nope", "/x", "y"]])
def test_a_wrong_call_is_exit_2(stub, args):
    proc, calls = stub(*args)
    assert proc.returncode == 2
    assert calls == []
