"""Every resource added by a patch must resolve in its project.

Android's resource merger fails a build when, for example, a layout references
``@dimen/foo`` and no ``foo`` dimen exists in the project or in the patch
series. That failure is easy to miss when the patch is only reviewed as text,
so resolve every reference on an added patch line against the pinned tree and
against resources created by the same series.

References are resolved by resource type: values resources by their
``name=`` attribute (including ``<item type="...">``) and file resources by
their file name. Framework references (``@android:``) are deliberately out of
scope: they resolve against the platform, not the patched project.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from harness import VENDOR, WORKSPACE
from lenos_projects import project_for

REFERENCE = re.compile(r"@(?!\+)([a-zA-Z0-9_]+)/([A-Za-z0-9_.]+)")
NAME = re.compile(r"<([a-zA-Z0-9_-]+)[^>]*\bname=\"([^\"]+)\"")
ITEM = re.compile(r"<item[^>]*\btype=\"([^\"]+)\"[^>]*\bname=\"([^\"]+)\"")
FILE_TYPES = {
    "drawable", "mipmap", "layout", "xml", "raw", "anim", "animator",
    "font", "menu", "navigation", "transition", "interpolator", "color",
}
SKIP_TYPES = {"android", "null", "empty", "id"}


def resource_type(parts: tuple[str, ...]) -> str | None:
    """Return the resource type for a ``res/<type>/...`` path, if any."""
    for i in range(len(parts) - 2, -1, -1):
        if parts[i] == "res":
            return parts[i + 1].split("-")[0]
    return None


def add_values_definitions(definitions: set[tuple[str, str]], text: str) -> None:
    for match in NAME.finditer(text):
        tag = match.group(1)
        if tag == "item":
            continue
        if tag in ("string-array", "integer-array"):
            tag = "array"
        definitions.add((tag, match.group(2)))
    for match in ITEM.finditer(text):
        definitions.add((match.group(1), match.group(2)))


def tree_definitions(project_dir: Path) -> set[tuple[str, str]]:
    definitions: set[tuple[str, str]] = set()
    for res_dir in project_dir.rglob("res"):
        if not res_dir.is_dir():
            continue
        for directory in res_dir.iterdir():
            if not directory.is_dir():
                continue
            typ = directory.name.split("-")[0]
            if typ == "values":
                for xml in directory.glob("*.xml"):
                    add_values_definitions(
                        definitions,
                        xml.read_text(encoding="utf-8", errors="replace"),
                    )
            elif typ in FILE_TYPES:
                for resource in directory.iterdir():
                    if resource.is_file():
                        definitions.add((typ, resource.name.split(".")[0]))
    return definitions


def patch_definitions(patch: Path) -> set[tuple[str, str]]:
    definitions: set[tuple[str, str]] = set()
    for line in patch.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("diff --git "):
            match = re.search(r" b/(.+)$", line)
            if match:
                parts = Path(match.group(1)).parts
                typ = resource_type(parts)
                if typ in FILE_TYPES:
                    definitions.add((typ, Path(match.group(1)).name.split(".")[0]))
        elif line.startswith("+") and not line.startswith("+++"):
            add_values_definitions(definitions, line)
    return definitions


class TestPatchResourceReferences(unittest.TestCase):
    def test_added_resource_references_resolve(self):
        if not WORKSPACE.is_dir():
            raise unittest.SkipTest(f"workspace missing: {WORKSPACE}")

        roots = (VENDOR / "patches", VENDOR / "patches-experimental")
        missing: list[str] = []
        for root in roots:
            for patch_dir in sorted(root.iterdir()):
                if not patch_dir.is_dir():
                    continue
                project = project_for(patch_dir.name)
                self.assertIsNotNone(
                    project, f"unknown patch project: {patch_dir.name}")
                project_dir = WORKSPACE / project
                if not project_dir.is_dir():
                    raise unittest.SkipTest(f"workspace project missing: {project}")
                definitions = tree_definitions(project_dir)
                patches = sorted(patch_dir.glob("*.patch"))
                for patch in patches:
                    definitions |= patch_definitions(patch)
                for patch in patches:
                    for line in patch.read_text(
                            encoding="utf-8", errors="replace").splitlines():
                        if not line.startswith("+") or line.startswith("+++"):
                            continue
                        for match in REFERENCE.finditer(line):
                            typ, name = match.groups()
                            if typ in SKIP_TYPES:
                                continue
                            if (typ, name) not in definitions:
                                missing.append(
                                    f"{patch_dir.name}/{patch.name}: @{typ}/{name}")
        self.assertEqual(missing, [], "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
