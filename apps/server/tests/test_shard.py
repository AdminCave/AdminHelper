# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""--shard K/N: the CI jobs together run every test exactly once (ci.yml, R-0950)."""

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import parse_shard, shard_of_each_file

SERVER = Path(__file__).resolve().parents[1]
FILES = ["tests/test_core_time.py", "tests/test_bounds.py", "tests/test_ip_filter.py"]


def _collected(*args):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *FILES,
            *args,
        ],
        cwd=SERVER,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return {line for line in result.stdout.splitlines() if "::" in line}


def test_the_shards_of_a_real_collection_are_disjoint_and_together_all_of_it():
    everything = _collected()
    first, second = _collected("--shard", "1/2"), _collected("--shard", "2/2")
    assert len({nodeid.split("::")[0] for nodeid in everything}) == len(FILES)
    assert first and second
    assert not first & second
    assert first | second == everything


def test_each_file_goes_whole_to_one_shard_and_the_load_is_balanced():
    counts = {"a.py": 10, "b.py": 7, "c.py": 4, "d.py": 3, "e.py": 1}
    shard = shard_of_each_file(counts, 2)
    assert set(shard) == set(counts)
    load = [sum(n for f, n in counts.items() if shard[f] == s) for s in range(2)]
    assert sorted(load) == [12, 13]


def test_the_split_does_not_depend_on_the_order_of_the_files():
    counts = {"a.py": 5, "b.py": 5, "c.py": 5}
    reordered = dict(reversed(list(counts.items())))
    assert shard_of_each_file(counts, 2) == shard_of_each_file(reordered, 2)


def test_more_shards_than_files_leaves_some_empty():
    assert sorted(shard_of_each_file({"a.py": 1}, 3).values()) == [0]


@pytest.mark.parametrize("value", ["0/2", "3/2", "2", "x/2", "1/x", "1/0", ""])
def test_a_shard_outside_1_to_n_is_refused(value):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_shard(value)


def test_k_of_n_is_parsed():
    assert parse_shard("2/3") == (2, 3)


def test_an_invalid_shard_ends_pytest_with_a_usage_error():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", FILES[0], "--shard", "3/2"],
        cwd=SERVER,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 4
    assert "--shard wants K/N" in result.stderr
