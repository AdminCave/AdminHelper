# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hermetic tests for scripts/release/changelog-assemble.py: fixtures in tmp_path only."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "changelog_assemble",
    pathlib.Path(__file__).resolve().parents[2] / "release" / "changelog-assemble.py",
)
assert _SPEC and _SPEC.loader
ca = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ca)

CHANGELOG = """# Changelog

Vorspann.

## [Unreleased]

### Added

- **Alt A:** zwei
  Zeilen.

### Fixed

- **Alt F:** eins.

## [1.0.0] - 2026-01-01

### Added

- **Release:** bleibt.
"""


def tree(tmp_path: pathlib.Path, fragments: dict[str, str]) -> pathlib.Path:
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    d = tmp_path / "changelog.d"
    d.mkdir()
    (d / "README.md").write_text("# Wie\n\nkein Fragment\n", encoding="utf-8")
    for name, text in fragments.items():
        (d / name).write_text(text, encoding="utf-8")
    return tmp_path


def run(root: pathlib.Path, *args: str) -> int:
    return ca.main(["--root", str(root), *args])


def test_fold_appends_to_the_subsection_adds_a_missing_one_and_keeps_the_rest(
    tmp_path: pathlib.Path,
) -> None:
    root = tree(
        tmp_path,
        {
            "b-zweig.md": "### Fixed\n\n- **Neu F2:** eins.\n",
            "a-zweig.md": "### Added\n\n- **Neu A:** eins.\n\n### Security\n\n- **Neu S:** eins.\n",
        },
    )
    assert run(root) == 0
    assert (
        (root / "CHANGELOG.md").read_text(encoding="utf-8")
        == """# Changelog

Vorspann.

## [Unreleased]

### Added

- **Alt A:** zwei
  Zeilen.
- **Neu A:** eins.

### Fixed

- **Alt F:** eins.
- **Neu F2:** eins.

### Security

- **Neu S:** eins.

## [1.0.0] - 2026-01-01

### Added

- **Release:** bleibt.
"""
    )
    assert sorted(f.name for f in (root / "changelog.d").iterdir()) == ["README.md"]


def test_check_reads_only(tmp_path: pathlib.Path) -> None:
    root = tree(tmp_path, {"a.md": "### Changed\n\n- x\n"})
    assert run(root, "--check") == 0
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == CHANGELOG
    assert (root / "changelog.d" / "a.md").exists()


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ("### Neu\n\n- x\n", "is not one of"),
        ("## [Unreleased]\n\n### Added\n\n- x\n", "is not one of"),
        ("- x ohne Ueberschrift\n", "text before the first ### heading"),
        ("### Added\n\n", "has no entry"),
        ("", "no ### heading"),
    ],
    ids=["unknown-heading", "section-heading", "no-heading", "empty-subsection", "empty"],
)
def test_a_fragment_out_of_format_is_exit_1_and_nothing_changes(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], text: str, says: str
) -> None:
    root = tree(tmp_path, {"ok.md": "### Added\n\n- gut\n", "z.md": text})
    assert run(root) == 1
    assert says in capsys.readouterr().err
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == CHANGELOG
    assert (root / "changelog.d" / "ok.md").exists()


def test_a_symlinked_fragment_is_exit_1(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tree(tmp_path, {})
    outside = tmp_path / "outside.md"
    outside.write_text("### Added\n\n- fremd\n", encoding="utf-8")
    (root / "changelog.d" / "link.md").symlink_to(outside)
    assert run(root) == 1
    assert "a symlink, not a fragment" in capsys.readouterr().err
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == CHANGELOG


def test_a_changelog_without_unreleased_is_exit_1_and_keeps_the_fragments(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tree(tmp_path, {"a.md": "### Added\n\n- x\n"})
    text = CHANGELOG.replace("## [Unreleased]\n", "")
    (root / "CHANGELOG.md").write_text(text, encoding="utf-8")
    assert run(root) == 1
    assert "no '## [Unreleased]' section" in capsys.readouterr().err
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == text
    assert (root / "changelog.d" / "a.md").exists()


def test_nothing_to_fold_changes_nothing(tmp_path: pathlib.Path) -> None:
    root = tree(tmp_path, {})
    assert run(root) == 0
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == CHANGELOG
