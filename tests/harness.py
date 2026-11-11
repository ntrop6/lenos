"""Shared test harness for lenOS patches.

Two kinds of checks:

1. ``LenosPatchTest`` — extracts the files a patch touches from the pinned
   workspace tree, applies the patch in a temporary directory and lets tests
   assert on the result (contents, Java syntax, XML well-formedness). This
   proves the patch itself is what we think it is.
2. ``TestPatchSeries`` — verifies that the whole series still applies to the
   pinned checkouts in the workspace (and can be reverse-applied), which
   catches upstream drift.

Java syntax is checked with tree-sitter when available (modern Java syntax,
0.23+). When the module is missing the check is skipped, never silently
"passed".
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from lenos_projects import alias_for  # noqa: E402

WORKSPACE = Path(os.environ.get(
    "LENOS_WORKSPACE",
    str(Path.home() / "lineage")))
VENDOR = Path(__file__).resolve().parent.parent

try:
    import tree_sitter
    import tree_sitter_java
    _JAVA_PARSER = tree_sitter.Parser(tree_sitter.Language(tree_sitter_java.language()))
except Exception:  # pragma: no cover - optional dependency
    _JAVA_PARSER = None


def java_syntax_errors(path: Path) -> int:
    if _JAVA_PARSER is None:
        raise unittest.SkipTest("tree-sitter-java not installed")
    tree = _JAVA_PARSER.parse(path.read_bytes())
    def walk(node):
        n = 1 if (node.type == "ERROR" or node.is_missing) else 0
        for child in node.children:
            n += walk(child)
        return n
    return walk(tree.root_node)


def patch_paths(patch: Path) -> list[str]:
    """Files the patch reads or writes, as tree-relative paths."""
    out = []
    for line in patch.read_text(encoding="utf-8").splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            p = line[4:].split("\t")[0].strip()
            if p == "/dev/null":
                continue
            if p.startswith("a/") or p.startswith("b/"):
                p = p[2:]
            if p not in out:
                out.append(p)
    return out


def added_lines(patch: Path, rel: str) -> str:
    """Return the added lines for one file in a patch.

    New files therefore come back as their full content. For modified files
    this is only the added hunks, which is enough for source-level feature
    checks that do not need the surrounding original.
    """
    marker = f"+++ b/{rel}"
    collecting = False
    out: list[str] = []
    for line in patch.read_text(encoding="utf-8").splitlines():
        if line.startswith("diff --git "):
            collecting = False
        elif line == marker:
            collecting = True
        elif collecting:
            if line.startswith("+") and not line.startswith("+++"):
                out.append(line[1:])
    return "\n".join(out)


def patch_created_paths(patch: Path) -> set[str]:
    """Files the patch creates (old side is /dev/null)."""
    created: set[str] = set()
    old_is_null = False
    for line in patch.read_text(encoding="utf-8").splitlines():
        if line.startswith("--- "):
            old_is_null = line[4:].split("\t")[0].strip() == "/dev/null"
        elif line.startswith("+++ "):
            p = line[4:].split("\t")[0].strip()
            if old_is_null and p not in ("", "/dev/null"):
                created.add(p[2:] if p.startswith("b/") else p)
            old_is_null = False
    return created


class LenosPatchTest(unittest.TestCase):
    """Apply one or more patches to a copy of the pinned files and assert."""

    PROJECT: str = ""
    PATCHES: list[str] = []
    #: extra files to copy into the sandbox even when no patch touches them
    EXTRA_FILES: list[str] = []

    sandbox: Path

    @classmethod
    def setUpClass(cls):
        if not cls.PROJECT:
            raise unittest.SkipTest("no PROJECT set")
        cls.sandbox = Path(tempfile.mkdtemp(prefix="lenos-test-"))
        cls.addClassCleanup(shutil.rmtree, cls.sandbox, ignore_errors=True)
        project_dir = WORKSPACE / cls.PROJECT
        if not project_dir.is_dir():
            raise unittest.SkipTest(f"workspace project missing: {project_dir}")

        files: list[str] = list(cls.EXTRA_FILES)
        created: set[str] = set()
        for name in cls.PATCHES:
            patch = VENDOR / "patches" / alias_for(cls.PROJECT) / name
            files += patch_paths(patch)
            created |= patch_created_paths(patch)

        for rel in files:
            src = project_dir / rel
            if not src.is_file():
                if rel in created:
                    continue  # git apply creates it in the sandbox
                raise AssertionError(f"pinned file missing in workspace tree: {cls.PROJECT}/{rel}")
            dst = cls.sandbox / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        # `git apply` works outside a repository, but needs a directory it is
        # allowed to operate in. Keep everything relative to the sandbox.
        for name in cls.PATCHES:
            patch = VENDOR / "patches" / alias_for(cls.PROJECT) / name
            proc = subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch)],
                                  cwd=cls.sandbox, capture_output=True, text=True)
            if proc.returncode != 0:
                raise AssertionError(f"patch failed to apply: {name}\n{proc.stderr}")

    # --- helpers ---------------------------------------------------------
    def text(self, rel: str) -> str:
        return (self.sandbox / rel).read_text(encoding="utf-8", errors="replace")

    def assert_contains(self, rel: str, *needles: str):
        body = self.text(rel)
        for needle in needles:
            self.assertIn(needle, body, f"{rel} is missing {needle!r}")

    def assert_not_contains(self, rel: str, *needles: str):
        body = self.text(rel)
        for needle in needles:
            self.assertNotIn(needle, body, f"{rel} still contains {needle!r}")

    def assert_java_syntax(self, rel: str):
        errors = java_syntax_errors(self.sandbox / rel)
        self.assertEqual(errors, 0, f"{rel}: {errors} Java parse errors after patching")

    def assert_xml(self, rel: str):
        ET.parse(self.sandbox / rel)

    def assert_balanced(self, rel: str):
        """Cheap sanity check for languages without a parser here."""
        body = self.text(rel)
        for open_c, close_c in (("{", "}"), ("(", ")"), ("[", "]")):
            self.assertEqual(body.count(open_c), body.count(close_c),
                             f"{rel}: unbalanced {open_c}{close_c}")


class TestPatchSeries(unittest.TestCase):
    """The patch series must pass --check against the pinned tree."""

    def test_series_check_passes(self):
        """--check is forward on a clean tree and reverse on an applied tree."""
        tool = VENDOR / "tools/lenos-patch.py"
        check = subprocess.run(
            [sys.executable, str(tool), "--tree", str(WORKSPACE), "--check"],
            capture_output=True, text=True)
        # already-applied patches report "skip (already applied)" and exit 0
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_no_stray_patches_outside_series(self):
        proot = VENDOR / "patches"
        for pdir in sorted(proot.iterdir()):
            if not pdir.is_dir():
                continue
            series_file = pdir / "series"
            self.assertTrue(series_file.is_file(), f"{pdir.name} has no series file")
            listed = {ln.strip() for ln in series_file.read_text().splitlines()
                      if ln.strip() and not ln.strip().startswith("#")}
            present = {f.name for f in pdir.glob("*.patch")}
            self.assertEqual(present - listed, set(),
                             f"{pdir.name}: patches exist but are not in series: "
                             f"{sorted(present - listed)}")
            self.assertEqual(listed - present, set(),
                             f"{pdir.name}: series lists missing patches: "
                             f"{sorted(listed - present)}")
