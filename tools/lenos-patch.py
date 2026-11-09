#!/usr/bin/env python3
"""lenos-patch — apply lenOS feature patches to a pinned LineageOS tree.

Design rules (see docs/build.md):

* Patches are ordinary unified diffs produced by ``git diff`` in the pinned
  upstream project. They are applied with ``git apply`` inside the project,
  never with fuzzy matching.
* A patch that does not apply is a hard error. Silently skipping a security
  feature because upstream moved a line is how you ship a broken OS.
* ``--check`` never writes. ``--reverse`` removes a feature (for bisecting).
* ``--reset`` returns the series' projects to their pinned revisions: it
  restores tracked files and deletes files the series creates (plain
  ``git checkout`` leaves those behind and then ``--check`` can never pass).
* Every project has ``patches/<project>/series`` listing patches in apply
  order; a patch not in the series is not applied.

Usage:
    lenos-patch.py --tree /path/to/lineage --check
    lenos-patch.py --tree /path/to/lineage --apply
    lenos-patch.py --tree /path/to/lineage --apply --project frameworks/base
    lenos-patch.py --tree /path/to/lineage --reverse --apply
    lenos-patch.py --tree /path/to/lineage --reset
    lenos-patch.py --tree /path/to/lineage --experimental --check
    lenos-patch.py --tree /path/to/lineage --experimental --apply
    lenos-patch.py --tree /path/to/lineage --experimental --reset
    lenos-patch.py --tree /path/to/lineage --require-applied
    lenos-patch.py --tree /path/to/lineage --experimental --require-applied
    lenos-patch.py --list [--experimental]

The experimental series is always applied **after** the stable 1.0 series and
must be checked/applied separately. It is not part of a default build.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lenos_projects import PROJECT_ALIASES, alias_for, project_for  # noqa: E402

HERE = Path(__file__).resolve().parent.parent  # vendor/lenos
STABLE_PATCH_ROOT = HERE / "patches"
EXPERIMENTAL_PATCH_ROOT = HERE / "patches-experimental"


def patch_root_for(experimental: bool) -> Path:
    return EXPERIMENTAL_PATCH_ROOT if experimental else STABLE_PATCH_ROOT


def patch_dir_for(project: str, root: Path) -> Path:
    return root / alias_for(project)


def series(project: str, root: Path) -> list[Path]:
    pdir = patch_dir_for(project, root)
    sfile = pdir / "series"
    if not sfile.is_file():
        return []
    out = []
    for line in sfile.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patch = pdir / line
        if not patch.is_file():
            raise SystemExit(f"ERROR: {project}: series lists missing patch {line}")
        out.append(patch)
    return out


def projects(root: Path) -> list[str]:
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir() or not (d / "series").is_file():
            continue
        project = project_for(d.name)
        if project is not None:
            out.append(project)
    return out


def git_apply(project_dir: Path, patch: Path, *, reverse: bool, check: bool) -> None:
    args = ["git", "apply", "--verbose"]
    if check:
        args.append("--check")
    if reverse:
        args.append("--reverse")
    # whitespace warnings on context lines are normal in AOSP; do not fail on them
    args += [str(patch)]
    proc = subprocess.run(args, cwd=project_dir, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            f"ERROR: {'reverse ' if reverse else ''}apply failed in {project_dir.name}:\n"
            f"  patch: {patch.name}\n  {proc.stderr.strip()}\n"
            "The tree does not match the pinned source revision. Fix the tree or update the\n"
            "patch set; do not ship with the feature silently missing."
        )
    if check:
        print(f"  ok    {project_dir.name}: {patch.name}")


def is_applied(project_dir: Path, patch: Path) -> bool:
    proc = subprocess.run(
        ["git", "apply", "--reverse", "--check", str(patch)],
        cwd=project_dir, capture_output=True, text=True)
    return proc.returncode == 0


def patch_paths(patch: Path) -> list[str]:
    """Every file path the patch touches, including rename/copy ends."""
    out: list[str] = []

    def add(p: str) -> None:
        p = p.split("\t")[0].strip()
        if p.startswith("a/") or p.startswith("b/"):
            p = p[2:]
        if p not in ("", "/dev/null") and p not in out:
            out.append(p)

    for line in patch.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                add(parts[2])
                add(parts[3])
        elif line.startswith("--- ") or line.startswith("+++ "):
            add(line[4:])
        elif line.startswith(("rename from ", "rename to ",
                              "copy from ", "copy to ")):
            add(line.split(" ", 2)[2])
    return out


def series_applied(project_dir: Path, patches: list[Path]) -> bool:
    """True if the whole series is applied.

    Reverse-checking one patch in isolation is not enough: a later patch can
    change the context of an earlier one, so its reverse check fails even
    though the series is fully applied. Reverse the series in reverse order in
    a throwaway copy of every touched file instead. This never writes to the
    real checkout.
    """
    if not patches:
        return True
    with tempfile.TemporaryDirectory(prefix="lenos-series-") as td:
        tmp = Path(td)
        for patch in patches:
            for rel in patch_paths(patch):
                src = project_dir / rel
                if not src.is_file():
                    continue
                dst = tmp / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        for patch in reversed(patches):
            proc = subprocess.run(
                ["git", "apply", "--reverse", "--whitespace=nowarn", str(patch)],
                cwd=tmp, capture_output=True, text=True)
            if proc.returncode != 0:
                return False
        return True


def series_check(
    project_dir: Path, patches: list[Path], *, reverse: bool = False
) -> None:
    """Verify a whole series in order without touching the real checkout.

    ``--check`` must be cumulative: later patches legitimately depend on
    context created by earlier ones. Checking each patch in isolation against
    the pristine tree only works when every patch is hand-trimmed to avoid its
    own series, which is brittle and hides real conflicts. Apply the series in
    a throwaway copy instead, exactly like ``--apply`` would.
    """
    if not patches:
        return
    with tempfile.TemporaryDirectory(prefix="lenos-check-") as td:
        tmp = Path(td)
        for patch in patches:
            for rel in patch_paths(patch):
                src = project_dir / rel
                if not src.is_file():
                    continue
                dst = tmp / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        ordered = list(reversed(patches)) if reverse else patches
        for patch in ordered:
            command = ["git", "apply", "--verbose", "--whitespace=nowarn"]
            if reverse:
                command.append("--reverse")
            command.append(str(patch))
            proc = subprocess.run(
                command, cwd=tmp, capture_output=True, text=True)
            if proc.returncode != 0:
                direction = "reverse " if reverse else ""
                raise SystemExit(
                    f"ERROR: {direction}check failed in {project_dir.name}:\n"
                    f"  patch: {patch.name}\n  {proc.stderr.strip()}\n"
                    "The series does not apply cumulatively to this tree. Fix the\n"
                    "tree or update the patch set; do not ship a half-patched build."
                )
            suffix = " (reverse)" if reverse else ""
            print(f"  ok    {project_dir.name}: {patch.name}{suffix}")


def created_paths(patch: Path) -> list[str]:
    """Files the patch creates or renames to, as project-relative paths."""
    out: list[str] = []
    old_is_null = False
    for line in patch.read_text(encoding="utf-8").splitlines():
        if line.startswith("--- "):
            old_is_null = line[4:].split("\t")[0].strip() == "/dev/null"
        elif line.startswith("+++ "):
            p = line[4:].split("\t")[0].strip()
            if old_is_null and p not in ("", "/dev/null"):
                out.append(p[2:] if p.startswith("b/") else p)
            old_is_null = False
        elif line.startswith(("rename to ", "copy to ")):
            p = line.split(" to ", 1)[1].strip()
            if p not in ("", "/dev/null"):
                out.append(p[2:] if p.startswith("b/") else p)
    return out


def classify_series(
    project_dir: Path, patches: list[Path]
) -> tuple[list[bool], bool]:
    """Return per-patch applied flags and whether the whole series is applied."""
    flags = [is_applied(project_dir, patch) for patch in patches]
    if all(flags):
        return flags, True
    if series_applied(project_dir, patches):
        # An earlier patch may no longer reverse on its own after a later
        # patch in the same file. The whole-series check is authoritative.
        return [True] * len(patches), True
    return flags, False


def reset_project(project: str, pdir: Path, patches: list[Path]) -> None:
    """Restore the pinned state: checkout tracked files, remove created files."""
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                           cwd=pdir, capture_output=True, text=True).stdout
    if dirty.strip():
        print(f"  WARNING {project}: discarding tracked edits:")
        for line in dirty.splitlines():
            print(f"    {line}")

    proc = subprocess.run(["git", "checkout", "--", "."],
                          cwd=pdir, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"ERROR: git checkout failed in {pdir}:\n{proc.stderr.strip()}")

    for patch in patches:
        for rel in created_paths(patch):
            f = pdir / rel
            if not f.exists():
                continue
            tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel],
                                     cwd=pdir, capture_output=True, text=True)
            if tracked.returncode == 0:
                raise SystemExit(
                    f"ERROR: {project}: series creates {rel} but it is tracked.\n"
                    "The patch set does not match the pinned revision; do not reset blindly.")
            f.unlink()
            print(f"  removed {project}: {rel}")
            parent = f.parent
            while parent != pdir and parent.is_dir():
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent

    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                            cwd=pdir, capture_output=True, text=True)
    if status.stdout.strip():
        raise SystemExit(
            f"ERROR: {project}: still modified after reset:\n{status.stdout.strip()}")
    print(f"  reset {project}: pinned state")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", help="LineageOS source tree root")
    ap.add_argument("--project", action="append", default=[],
                    help="limit to this project path (repeatable)")
    ap.add_argument("--check", action="store_true", help="verify patches apply, do not write")
    ap.add_argument("--apply", action="store_true", help="apply patches")
    ap.add_argument("--reverse", action="store_true", help="reverse direction")
    ap.add_argument("--list", action="store_true", help="list project/patch pairs")
    ap.add_argument("--status", action="store_true",
                    help="report applied/not applied per patch (needs --tree)")
    ap.add_argument("--require-applied", action="store_true",
                    help="exit non-zero unless the whole series is applied (needs --tree)")
    ap.add_argument("--reset", action="store_true",
                    help="restore the series' projects to the pinned revision "
                         "(git checkout + remove files the series created)")
    ap.add_argument("--experimental", action="store_true",
                    help="use patches-experimental/ (apply only after the stable series)")
    args = ap.parse_args()

    root = patch_root_for(args.experimental)

    if args.list:
        for project in projects(root):
            if args.project and project not in args.project:
                continue
            for patch in series(project, root):
                print(f"{project}\t{patch.name}")
        return 0

    actions = (args.apply, args.check, args.status,
               args.require_applied, args.reset)
    if sum(bool(a) for a in actions) != 1:
        ap.error("choose exactly one of --check/--apply/--status/"
                 "--require-applied/--reset")
    if args.reverse and not (args.apply or args.check):
        ap.error("--reverse is a modifier for --check or --apply")

    if not args.tree:
        ap.error("--tree is required unless --list")
    tree = Path(args.tree).resolve()

    targets = args.project or projects(root)
    if not targets:
        raise SystemExit("ERROR: no projects with a series file found in " + str(root))

    if args.apply:
        # Verify every target project before writing to any of them. Without
        # this, a patch failure late in the series leaves an earlier project
        # already modified and the tree in a half-applied state.
        for project in targets:
            patches = series(project, root)
            if not patches:
                continue
            pdir = tree / project
            if not (pdir / ".git").exists() and not (pdir / ".git").is_file():
                continue
            flags, fully_applied = classify_series(pdir, patches)
            if fully_applied:
                continue
            if any(flags):
                raise SystemExit(
                    f"ERROR: {project}: partially applied series. Reset it first:\n"
                    f"  python3 tools/lenos-patch.py --tree {tree} --reset "
                    f"--project {project}"
                )
            if args.reverse:
                continue
            series_check(pdir, patches)

    rc = 0
    for project in targets:
        patches = series(project, root)
        if not patches:
            print(f"  skip  {project}: no patches")
            continue
        pdir = tree / project
        if not (pdir / ".git").exists() and not (pdir / ".git").is_file():
            print(f"  WARN  {project}: not a git checkout under {tree}; skipping")
            rc = 1
            continue
        if args.reset:
            reset_project(project, pdir, patches)
            continue
        if args.require_applied:
            if series_applied(pdir, patches):
                print(f"  applied series {project}: {len(patches)} patches")
            else:
                print(f"  NOT applied  {project}: series is missing or partial")
                rc = 1
            continue

        flags, fully_applied = classify_series(pdir, patches)
        if args.status:
            for patch, applied in zip(patches, flags):
                state = "applied" if applied else "missing"
                print(f"  {state:7} {project}: {patch.name}")
            continue
        if args.check:
            if fully_applied:
                for patch in patches:
                    print(f"  skip  {project}: {patch.name} (already applied)")
                continue
            if any(flags):
                raise SystemExit(
                    f"ERROR: {project}: partially applied series. Reset it first:\n"
                    f"  python3 tools/lenos-patch.py --tree {tree} --reset "
                    f"--project {project}"
                )
            if args.reverse:
                for patch in patches:
                    print(f"  skip(reverse) {project}: {patch.name} (not applied)")
                continue
            series_check(pdir, patches)
            continue
        if args.reverse:
            if not fully_applied:
                if any(flags):
                    raise SystemExit(
                        f"ERROR: {project}: partially applied series. Reset it first:\n"
                        f"  python3 tools/lenos-patch.py --tree {tree} --reset "
                        f"--project {project}"
                    )
                for patch in patches:
                    print(f"  skip(reverse) {project}: {patch.name} (not applied)")
                continue
            series_check(pdir, patches, reverse=True)
            for patch in reversed(patches):
                git_apply(pdir, patch, reverse=True, check=False)
                print(f"  reversed {project}: {patch.name}")
            continue
        if fully_applied:
            for patch in patches:
                print(f"  skip  {project}: {patch.name} (already applied)")
            continue
        if any(flags):
            raise SystemExit(
                f"ERROR: {project}: partially applied series. Reset it first:\n"
                f"  python3 tools/lenos-patch.py --tree {tree} --reset "
                f"--project {project}"
            )
        for patch in patches:
            git_apply(pdir, patch, reverse=False, check=False)
            print(f"  applied {project}: {patch.name}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
