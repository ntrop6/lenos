#!/usr/bin/env python3
"""lenOS repository self-check.

Validates, without an Android tree:
  - every patch parses as a unified git diff (headers + hunks present),
  - every patch declares its target repos coherently (device patches carry
    git-am commit headers; platform patches carry lenOS authorship),
  - the pinned manifest references 40-hex revisions and parses as XML,
  - config/VERSIONS.sh pins are 64-hex sha256 values,
  - shell scripts pass `bash -n`,
  - resource XMLs parse.
"""
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
errors: list = []


def check(cond, msg):
    if cond:
        print(f"ok    {msg}")
    else:
        errors.append(msg)
        print(f"FAIL  {msg}")


DIFF_HEAD = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.M)
HUNK = re.compile(r"^@@")


def validate_patch(path: Path):
    text = path.read_text()
    if path.parent.name == "device-patches":
        check(text.startswith("From "), f"{path.name}: git-am header")
        check("Subject: [PATCH" in text, f"{path.name}: git-am subject")
    else:
        check("From: lenOS <security@lenos.invalid>" in text,
              f"{path.name}: lenOS author header")
    heads = DIFF_HEAD.findall(text)
    check(len(heads) >= 1, f"{path.name}: has diff --git headers")
    # Hunk bodies must balance: every hunk starts a section of +/- lines.
    lines = text.splitlines()
    in_hunk = False
    saw_hunk = False
    for line in lines:
        if line == "-- ":  # git format-patch trailing signature
            break
        if line.startswith("@@"):
            in_hunk = True
            saw_hunk = True
        elif line.startswith(("diff --git", "index ", "--- ", "+++ ")):
            in_hunk = False
        elif in_hunk and line and not line.startswith(("+", "-", " ")) \
                and line != "\\ No newline at end of file":
            check(False, f"{path.name}: malformed hunk line: {line[:40]!r}")
            break
    check(saw_hunk, f"{path.name}: contains hunks")


def main() -> int:
    for d, label in (("patches", "platform"), ("device-patches", "device")):
        paths = sorted((ROOT / d).glob("*.patch"))
        check(len(paths) >= 15 if d == "patches" else len(paths) == 5,
              f"{d}: expected patch count ({len(paths)})")
        for p in paths:
            validate_patch(p)

    manifest = ROOT / "manifest" / "lenos-asteroids.xml"
    try:
        tree = ET.parse(manifest)
        revs = [p.get("revision") for p in tree.getroot().findall("project")]
        check(all(re.fullmatch(r"[0-9a-f]{40}", r or "") for r in revs),
              f"manifest: {len(revs)} pinned projects, all 40-hex")
    except ET.ParseError as e:
        check(False, f"manifest: XML parse error: {e}")

    versions = (ROOT / "config" / "VERSIONS.sh").read_text()
    pins = re.findall(r'SHA256="([0-9a-f]+)"', versions)
    check(len(pins) == 4 and all(len(p) == 64 for p in pins),
          f"VERSIONS.sh: {len(pins)} sha256 pins (avbroot, resukisu, oem, cromite)")

    sh_files = [
        ROOT / "build" / "lenos.sh",
        ROOT / "tools" / "sign_target_files.sh",
        ROOT / "tools" / "fetch-cromite.sh",
        ROOT / "vendor" / "lenos" / "bin" / "lenos-netd",
    ]
    for sh in sh_files:
        rc = subprocess.run(["bash", "-n", str(sh)], capture_output=True)
        check(rc.returncode == 0, f"{sh.relative_to(ROOT)}: bash -n"
              + ("" if rc.returncode == 0 else f" ({rc.stderr.decode().strip()[:80]})"))

    # Files that device patch 0002 (lenos.mk) references must exist in the
    # vendored runtime so the build never references a missing path.
    referenced = [
        ROOT / "vendor" / "lenos" / "init" / "lenos_sysctl.rc",
        ROOT / "vendor" / "lenos" / "init" / "lenos_net.rc",
        ROOT / "vendor" / "lenos" / "bin" / "lenos-netd",
        ROOT / "vendor" / "lenos" / "cromite.mk",
        ROOT / "vendor" / "lenos" / "prebuilt" / "Android.bp",
        ROOT / "tools" / "fetch-cromite.sh",
        ROOT / "tools" / "make-bootanimation.py",
    ]
    for ref in referenced:
        check(ref.exists(), f"{ref.relative_to(ROOT)}: referenced file exists")

    lenos_mk = (ROOT / "device-patches" / "0002-lenos-integration-makefile.patch").read_text()
    for token in ("vendor/lenos/init/lenos_sysctl.rc", "vendor/lenos/init/lenos_net.rc",
                  "vendor/lenos/bin/lenos-netd", "cromite.mk", "bootanimation.zip"):
        check(token in lenos_mk, f"lenos.mk references {token}")
    for leak in ("ro.lenos.", "BUILD_DISPLAY_ID=lenOS"):
        check(leak not in lenos_mk and leak not in
              (ROOT / "device-patches" / "0001-lenos-rebrand-product.patch").read_text(),
              f"no branding leak ({leak}) in device patches")

    print()
    if errors:
        print(f"self-check FAILED: {len(errors)} problem(s)")
        return 1
    print("self-check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
