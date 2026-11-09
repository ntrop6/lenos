"""The patchkit `--check` mode must be cumulative and non-destructive.

Later patches in a series legitimately depend on context created by earlier
ones. Checking each patch in isolation against the pristine tree only works
when every patch is hand-trimmed to avoid its own series, which is brittle and
hides real conflicts. These tests build a two-patch stack where patch 2 depends
on patch 1 and run the real tool through an isolated patch root.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from harness import VENDOR

TOOL = VENDOR / "tools" / "lenos-patch.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("lenos_patch_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return proc.stdout


class TestCumulativeCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lenos-check-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "tree" / "test" / "project"
        self.project.mkdir(parents=True)
        git(self.project, "init", "--quiet")
        (self.project / "values.txt").write_text(
            "one\ntwo\nthree\n", encoding="utf-8"
        )
        git(self.project, "add", "-A")
        git(
            self.project,
            "-c",
            "user.email=lenos@test",
            "-c",
            "user.name=lenos",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "base",
        )

        patches = self.root / "patches" / "test_project"
        patches.mkdir(parents=True)
        first = patches / "0001-first.patch"
        second = patches / "0002-second.patch"
        base_commit = git(self.project, "rev-parse", "HEAD").strip()
        (self.project / "values.txt").write_text(
            "ONE\ntwo\nthree\n", encoding="utf-8"
        )
        first.write_text(git(self.project, "diff"), encoding="utf-8")
        git(self.project, "checkout", "--", "values.txt")
        git(self.project, "apply", str(first))
        git(
            self.project,
            "-c",
            "user.email=lenos@test",
            "-c",
            "user.name=lenos",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-am",
            "first",
        )
        (self.project / "values.txt").write_text(
            "ONE\nTWO\nthree\n", encoding="utf-8"
        )
        second.write_text(git(self.project, "diff"), encoding="utf-8")
        git(self.project, "reset", "--hard", base_commit)
        (patches / "series").write_text(
            "0001-first.patch\n0002-second.patch\n", encoding="utf-8"
        )
        self.patch_root = patches.parent
        self.tool = load_tool()

    def run_check(self) -> int:
        old_root = self.tool.STABLE_PATCH_ROOT
        old_argv = sys.argv
        self.tool.STABLE_PATCH_ROOT = self.patch_root
        sys.argv = [
            "lenos-patch.py",
            "--tree",
            str(self.root / "tree"),
            "--check",
            "--project",
            "test/project",
        ]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return self.tool.main()
        finally:
            self.tool.STABLE_PATCH_ROOT = old_root
            sys.argv = old_argv

    def test_stacked_patches_check_against_a_pristine_tree(self):
        self.assertEqual((self.project / "values.txt").read_text(), "one\ntwo\nthree\n")
        self.assertEqual(self.run_check(), 0)
        # --check is read-only.
        self.assertEqual((self.project / "values.txt").read_text(), "one\ntwo\nthree\n")

    def test_partial_apply_is_reported_instead_of_half_checked(self):
        git(self.project, "apply", str(self.patch_root / "test_project" / "0001-first.patch"))
        with self.assertRaises(SystemExit) as caught:
            self.run_check()
        self.assertIn("partially applied", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
