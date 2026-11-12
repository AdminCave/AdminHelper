# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""--shard K/N: the CI jobs together run every test exactly once (ci.yml, R-0950)."""

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from tests.conftest import (
    load_shard_weights,
    parse_shard,
    shard_of_each_file,
    shard_weights,
)
from tests.shard_weights import measure, render

SERVER = Path(__file__).resolve().parents[1]
FILES = ["tests/test_core_time.py", "tests/test_bounds.py", "tests/test_ip_filter.py"]


def _collected(*args, files=FILES):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *files,
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


def _manifest(tmp_path, shard, *args, files=FILES):
    path = tmp_path / f"manifest-{shard.replace('/', '-')}-{len(files)}.json"
    _collected("--shard", shard, "--shard-manifest", str(path), *args, files=files)
    return json.loads(path.read_text())


def test_the_shards_of_one_collection_write_the_same_manifest(tmp_path):
    first, second = _manifest(tmp_path, "1/2"), _manifest(tmp_path, "2/2")
    assert (first["shard"], second["shard"]) == ("1/2", "2/2")
    assert first["count"] == second["count"] == len(_collected())
    assert first["sha256"] == second["sha256"]


def test_a_different_collection_changes_the_manifest(tmp_path):
    whole = _manifest(tmp_path, "1/2")
    fewer = _manifest(tmp_path, "1/2", files=FILES[:-1])
    assert fewer["count"] < whole["count"]
    assert fewer["sha256"] != whole["sha256"]


def test_the_shards_split_what_is_left_after_a_keyword_filter(tmp_path):
    # Leaves part of test_bounds.py and part of test_ip_filter.py, none of test_core_time.py.
    filtered = _collected("-k", "reject or invalid")
    assert filtered and filtered < _collected()
    first = _collected("--shard", "1/2", "-k", "reject or invalid")
    second = _collected("--shard", "2/2", "-k", "reject or invalid")
    assert not first & second
    assert first | second == filtered
    assert _manifest(tmp_path, "1/2", "-k", "reject or invalid")["count"] == len(filtered)


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


def test_a_file_weighs_its_tests_times_its_seconds_per_test():
    table = {"tests/test_a.py": (10.0, 5), "tests/test_b.py": (2.0, 5)}
    weights = shard_weights({"tests/test_a.py": 2, "tests/test_b.py": 5}, table)
    assert weights == pytest.approx({"tests/test_a.py": 4.0, "tests/test_b.py": 2.0})


def test_a_file_the_table_does_not_know_gets_the_mean_seconds_per_test():
    table = {"tests/test_a.py": (10.0, 5), "tests/test_b.py": (2.0, 5)}
    assert shard_weights({"tests/test_new.py": 3}, table) == pytest.approx(
        {"tests/test_new.py": 3 * 12.0 / 10}
    )


def test_one_slow_file_gets_a_shard_of_its_own():
    # By count the slow file would join two fast ones on one shard.
    table = {"slow.py": (60.0, 2), **{f"fast{i}.py": (5.0, 10) for i in range(4)}}
    counts = {name: tests for name, (_, tests) in table.items()}
    by_count = shard_of_each_file(counts, 2)
    assert sum(by_count[name] == by_count["slow.py"] for name in counts) == 3
    shard = shard_of_each_file(shard_weights(counts, table), 2)
    assert [name for name in counts if shard[name] == shard["slow.py"]] == ["slow.py"]


def test_without_a_table_each_test_weighs_one(tmp_path):
    counts = {"a.py": 3, "b.py": 1}
    assert load_shard_weights(tmp_path / "missing.toml") == {}
    assert shard_weights(counts, {}) == counts
    assert shard_weights(counts, {"a.py": (0.0, 3)}) == counts


def test_the_weighted_split_does_not_depend_on_the_order_of_the_files():
    # b.py and c.py weigh the same, 2.0: the tie breaks by name, not by order.
    table = {"a.py": (4.0, 2), "b.py": (2.0, 4), "c.py": (2.0, 1)}
    counts = {"a.py": 2, "b.py": 4, "c.py": 1, "d.py": 3}
    reordered = dict(reversed(list(counts.items())))
    assert shard_of_each_file(shard_weights(counts, table), 2) == shard_of_each_file(
        shard_weights(reordered, dict(reversed(list(table.items())))), 2
    )


def test_the_table_in_the_tree_names_test_files_with_their_time():
    table = load_shard_weights()
    assert table
    for name, (seconds, tests) in table.items():
        assert re.fullmatch(r"tests/test_\w+\.py", name), name
        assert seconds >= 0 and tests > 0, name
    header = (SERVER / "tests" / "shard_weights.toml").read_text()
    assert "python -m tests.shard_weights" in header


def _junit(path, *cases):
    path.write_text(
        "<testsuites><testsuite>"
        + "".join(f'<testcase classname="{c}" name="t" time="{t}"/>' for c, t in cases)
        + "</testsuite></testsuites>"
    )
    return str(path)


def test_the_generator_sums_the_shards_of_a_run_per_file(tmp_path):
    first = _junit(tmp_path / "1.xml", ("tests.test_a", 1.5), ("tests.test_a.TestX", 0.25))
    second = _junit(tmp_path / "2.xml", ("tests.test_b", 2.0))
    files = measure([first, second])
    assert files == {"tests/test_a.py": (1.75, 2), "tests/test_b.py": (2.0, 1)}
    table = tmp_path / "shard_weights.toml"
    table.write_text(render("run 1", files))
    assert load_shard_weights(table) == files
    assert "# Source: run 1" in table.read_text()


def test_the_generator_runs_as_a_module(tmp_path):
    xml = _junit(tmp_path / "1.xml", ("tests.test_a", 0.5))
    result = subprocess.run(
        [sys.executable, "-m", "tests.shard_weights", "run 1", xml],
        cwd=SERVER,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert tomllib.loads(result.stdout)["files"] == {
        "tests/test_a.py": {"seconds": 0.5, "tests": 1}
    }


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
