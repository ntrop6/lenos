#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare and verify opt-in root init_boot images for lenOS.

Root is deliberately a post-build transform:

* the normal LineageOS build stays rootless;
* this tool extracts init_boot from the already signed base OTA;
* a pinned x86_64 patcher injects the pinned manager's LKM and ksuinit;
* BakaSU payloads are read from the signed manager APK's embedded ksud asset;
* avbroot checks the resulting ramdisk;
* the caller re-signs the complete OTA with the user's AVB/OTA keys.

No phone, ADB, fastboot, or flashing is involved here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
import zlib
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_PROFILES = TOOLS_DIR / "root-managers.json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"\bavbroot\s+(\d+)\.(\d+)\.(\d+)\b")
BOARD_SIZE = re.compile(
    r"^\s*BOARD_INIT_BOOT_IMAGE_PARTITION_SIZE\s*:?=\s*(0x[0-9a-fA-F]+|[0-9]+)\s*$"
)
MIN_AVBROOT = (3, 33, 0)
ROOT_MODES = frozenset({"bakasu", "kernelsu"})
MAX_EMBEDDED_PAYLOAD = 32 * 1024 * 1024


class RootError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_atomic(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp.{os.getpid()}")
    try:
        temp.write_bytes(data)
        temp.chmod(mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_text(path: Path, text: str, mode: int = 0o644) -> None:
    write_atomic(path, text.encode("utf-8"), mode)


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RootError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RootError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RootError(f"{path} must contain a JSON object")
    return data


def require_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value.lower()):
        raise RootError(f"{label} is not a SHA-256 value")
    return value.lower()


def asset_filename(asset: dict[str, Any]) -> str:
    name = asset.get("file") or asset.get("name")
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise RootError("asset filename is missing or unsafe")
    return name


def validate_payload_asset(
    asset: Any, label: str, *, manager: bool = False
) -> dict[str, Any]:
    if not isinstance(asset, dict):
        raise RootError(f"{label} is missing")
    require_hex(asset.get("sha256"), f"{label}.sha256")
    if not isinstance(asset.get("name"), str) or not asset["name"]:
        raise RootError(f"{label} has no name")
    asset_filename(asset)
    if manager:
        url = asset.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise RootError(f"{label} has no HTTPS URL")
        require_hex(asset.get("cert_sha256"), f"{label}.cert_sha256")
        cert_size = asset.get("cert_size")
        if (
            not isinstance(cert_size, int)
            or isinstance(cert_size, bool)
            or cert_size <= 0
        ):
            raise RootError(f"{label} has no certificate size")
        return asset

    require_hex(asset.get("member_sha256"), f"{label}.member_sha256")
    embedded = asset.get("embedded")
    if embedded is not None:
        if not isinstance(embedded, dict):
            raise RootError(f"{label}.embedded is malformed")
        if embedded.get("asset") != "manager":
            raise RootError(f"{label}.embedded must come from the manager")
        member = embedded.get("member")
        if (
            not isinstance(member, str)
            or not member
            or Path(member).is_absolute()
            or ".." in Path(member).parts
        ):
            raise RootError(f"{label}.embedded.member is missing or unsafe")
        require_hex(embedded.get("sha256"), f"{label}.embedded.sha256")
        offset = embedded.get("offset")
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or offset < 0
        ):
            raise RootError(f"{label}.embedded.offset is invalid")
        if embedded.get("compression") not in ("raw-deflate", "deflate"):
            raise RootError(f"{label}.embedded.compression is unsupported")
        if asset["sha256"].lower() != asset["member_sha256"].lower():
            raise RootError(
                f"{label}.sha256 must equal member_sha256 for an embedded payload"
            )
    else:
        url = asset.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise RootError(f"{label} has no HTTPS URL")
    member = asset.get("member")
    if member is not None and (not isinstance(member, str) or not member):
        raise RootError(f"{label} has an invalid member")
    return asset


def load_profiles(path: Path, mode: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data = load_json(path)
    if data.get("schema") != 1:
        raise RootError(f"unsupported root manager profile schema in {path}")
    kmi = data.get("kmi")
    arch = data.get("arch")
    if not isinstance(kmi, str) or not kmi:
        raise RootError(f"{path} has no KMI")
    if arch != "aarch64":
        raise RootError(f"{path} must target aarch64")
    patcher = data.get("patcher")
    if not isinstance(patcher, dict):
        raise RootError(f"{path} has no patcher")
    require_hex(patcher.get("sha256"), "patcher sha256")
    if not isinstance(patcher.get("url"), str):
        raise RootError(f"{path} patcher has no URL")
    if not isinstance(patcher.get("name"), str):
        raise RootError(f"{path} patcher has no name")
    asset_filename(patcher)

    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or mode not in profiles:
        raise RootError(f"root profile {mode!r} is not defined in {path}")
    profile = profiles[mode]
    if not isinstance(profile, dict):
        raise RootError(f"root profile {mode!r} is malformed")
    validate_payload_asset(profile.get("manager"), f"{mode}.manager", manager=True)
    validate_payload_asset(profile.get("lkm"), f"{mode}.lkm")
    validate_payload_asset(profile.get("init"), f"{mode}.init")
    return data, profile


def download(url: str, destination: Path, expected: str, *, executable: bool = False) -> Path:
    expected = expected.lower()
    if destination.is_file() and sha256_file(destination) == expected:
        if executable:
            destination.chmod(0o755)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    temporary = destination.with_name(destination.name + f".part.{os.getpid()}")
    try:
        for attempt in range(1, 4):
            try:
                print(f"downloading {url}", file=sys.stderr)
                request = urllib.request.Request(
                    url, headers={"User-Agent": "lenos-root/1.0"}
                )
                with urllib.request.urlopen(request, timeout=120) as response:
                    with temporary.open("wb") as handle:
                        shutil.copyfileobj(response, handle, 1024 * 1024)
                actual = sha256_file(temporary)
                if actual != expected:
                    raise RootError(
                        f"download hash mismatch for {destination.name}: "
                        f"{actual} != {expected}"
                    )
                os.replace(temporary, destination)
                if executable:
                    destination.chmod(0o755)
                return destination
            except (OSError, urllib.error.URLError, RootError) as exc:
                print(
                    f"download attempt {attempt} failed for {destination.name}: {exc}",
                    file=sys.stderr,
                )
                if attempt == 3:
                    raise RootError(f"could not download {url}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    raise RootError(f"could not download {url}")


def extract_member(
    archive: Path, member: str, destination: Path, expected: str, *, executable: bool = False
) -> Path:
    if not archive.is_file():
        raise RootError(f"missing archive: {archive}")
    try:
        with zipfile.ZipFile(archive) as zf:
            try:
                payload = zf.read(member)
            except KeyError as exc:
                raise RootError(f"{archive.name} does not contain {member}") from exc
    except (OSError, zipfile.BadZipFile) as exc:
        raise RootError(f"cannot read {archive.name}: {exc}") from exc
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected.lower():
        raise RootError(
            f"member hash mismatch for {member}: {actual} != {expected.lower()}"
        )
    write_atomic(destination, payload, 0o755 if executable else 0o644)
    return destination


def extract_embedded_asset(
    manager: Path,
    asset: dict[str, Any],
    destination: Path,
    *,
    executable: bool = False,
) -> Path:
    """Extract a raw-DEFLATE payload embedded in the manager's ksud asset."""
    embedded = asset.get("embedded")
    if not isinstance(embedded, dict):
        raise RootError(f"{asset.get('name', 'payload')} is not embedded")
    member = embedded.get("member")
    if not isinstance(member, str) or not member:
        raise RootError("embedded asset member is missing")
    if not manager.is_file():
        raise RootError(f"missing manager APK: {manager}")
    try:
        with zipfile.ZipFile(manager) as zf:
            try:
                blob = zf.read(member)
            except KeyError as exc:
                raise RootError(f"{manager.name} does not contain {member}") from exc
    except (OSError, zipfile.BadZipFile) as exc:
        raise RootError(f"cannot read {manager.name}: {exc}") from exc
    actual = hashlib.sha256(blob).hexdigest()
    expected = require_hex(embedded.get("sha256"), "embedded archive sha256")
    if actual != expected:
        raise RootError(
            f"embedded archive hash mismatch for {member}: {actual} != {expected}"
        )
    offset = embedded["offset"]
    if offset >= len(blob):
        raise RootError(f"embedded payload offset {offset} is outside {member}")
    decompressor = zlib.decompressobj(-15)
    try:
        payload = decompressor.decompress(
            blob[offset:], MAX_EMBEDDED_PAYLOAD + 1
        )
    except zlib.error as exc:
        raise RootError(f"cannot inflate embedded payload at offset {offset}: {exc}") from exc
    if len(payload) > MAX_EMBEDDED_PAYLOAD:
        raise RootError("embedded payload exceeds the size limit")
    if not decompressor.eof:
        raise RootError("embedded payload is truncated or exceeds the size limit")
    actual = hashlib.sha256(payload).hexdigest()
    expected = require_hex(asset.get("member_sha256"), "embedded payload sha256")
    if actual != expected:
        raise RootError(
            f"embedded payload hash mismatch: {actual} != {expected}"
        )
    write_atomic(destination, payload, 0o755 if executable else 0o644)
    return destination


def verify_manager(path: Path, asset: dict[str, Any]) -> tuple[int, str]:
    try:
        from apk_signing_cert import ApkError, verify_certificate
    except ImportError as exc:
        raise RootError("apk_signing_cert.py is missing next to lenos_root.py") from exc
    try:
        size, digest = verify_certificate(
            path,
            expect_size=asset["cert_size"],
            expect_sha256=asset["cert_sha256"],
        )
    except (OSError, ApkError, KeyError) as exc:
        raise RootError(f"manager APK signer verification failed: {exc}") from exc
    return size, digest


def require_avbroot(path: Path) -> str:
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RootError(f"missing executable avbroot: {path}")
    result = subprocess.run(
        [str(path), "--version"],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    text = (result.stdout or "") + (result.stderr or "")
    match = VERSION.search(text)
    if result.returncode != 0 or not match:
        raise RootError(f"cannot determine avbroot version from {path}")
    version = tuple(int(part) for part in match.groups())
    if version < MIN_AVBROOT:
        want = ".".join(str(part) for part in MIN_AVBROOT)
        got = ".".join(str(part) for part in version)
        raise RootError(f"avbroot {want}+ is required; found {got}")
    return ".".join(str(part) for part in version)


def run_checked(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        if len(output) > 4000:
            output = output[-4000:]
        raise RootError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{output}"
        )
    return result.stdout or ""


def extract_init_boot(avbroot: Path, ota: Path, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            str(avbroot),
            "ota",
            "extract",
            "--input",
            str(ota),
            "--directory",
            str(directory),
            "--partition",
            "init_boot",
        ]
    )
    image = directory / "init_boot.img"
    if not image.is_file() or image.stat().st_size == 0:
        raise RootError(f"{ota} did not contain an init_boot image")
    return image


def _field(block: str, name: str) -> str | None:
    match = re.search(rf'^\s*{re.escape(name)}\s*=\s*"([^"]*)"', block, re.M)
    return match.group(1) if match else None


def parse_cpio_info(path: Path) -> dict[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    entries: dict[str, dict[str, str]] = {}
    for block in text.split("[[entries]]")[1:]:
        raw_path = _field(block, "path")
        if not raw_path:
            continue
        key = raw_path[2:] if raw_path.startswith("./") else raw_path
        entry = {
            "file_type": _field(block, "file_type") or "",
            "file_mode": _field(block, "file_mode") or "",
        }
        entries[key] = entry
    return entries


def _is_executable(entry: dict[str, str]) -> bool:
    mode = entry.get("file_mode", "")
    try:
        return bool(int(mode, 8) & 0o111)
    except ValueError:
        return False


def inspect_ramdisk(
    avbroot: Path,
    image: Path,
    mode: str,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if mode not in {"stock", *ROOT_MODES}:
        raise RootError(f"unsupported image mode: {mode}")
    with tempfile.TemporaryDirectory(prefix="lenos-root-ramdisk-") as temporary:
        temp = Path(temporary)
        run_checked(
            [
                str(avbroot),
                "boot",
                "unpack",
                "--input",
                str(image),
                "--no-output-kernel",
                "--no-output-second",
                "--no-output-recovery-dtbo",
                "--no-output-dtb",
                "--no-output-bootconfig",
                "--output-ramdisk-prefix",
                "ramdisk.img.",
                "--quiet",
            ],
            cwd=temp,
        )
        ramdisks = sorted(temp.glob("ramdisk.img.*"))
        if len(ramdisks) != 1:
            raise RootError(f"{image} does not contain exactly one init_boot ramdisk")
        info = temp / "cpio.toml"
        tree = temp / "tree"
        run_checked(
            [
                str(avbroot),
                "cpio",
                "unpack",
                "--input",
                str(ramdisks[0]),
                "--output-info",
                str(info),
                "--output-tree",
                str(tree),
                "--quiet",
            ]
        )
        entries = parse_cpio_info(info)

        def entry(name: str) -> dict[str, str]:
            value = entries.get(name)
            if value is None:
                raise RootError(f"ramdisk is missing {name}")
            return value

        init = entry("init")
        if init["file_type"] != "Regular" or not _is_executable(init):
            raise RootError("ramdisk init is not an executable regular file")
        init_hash = sha256_file(tree / "init")

        if mode == "stock":
            if "kernelsu.ko" in entries or "init.real" in entries:
                raise RootError(
                    "init_boot is already patched (kernelsu.ko or init.real present)"
                )
            return {"init_sha256": init_hash}

        init_real = entry("init.real")
        module = entry("kernelsu.ko")
        if init_real["file_type"] != "Regular" or not _is_executable(init_real):
            raise RootError("ramdisk init.real is not an executable regular file")
        if module["file_type"] != "Regular":
            raise RootError("ramdisk kernelsu.ko is not a regular file")
        init_real_hash = sha256_file(tree / "init.real")
        module_hash = sha256_file(tree / "kernelsu.ko")
        result = {
            "init_sha256": init_hash,
            "init_real_sha256": init_real_hash,
            "lkm_sha256": module_hash,
        }
        if state:
            expected = {
                "init_sha256": state.get("ksuinit_sha256"),
                "init_real_sha256": state.get("stock_init_sha256"),
                "lkm_sha256": state.get("lkm_sha256"),
            }
            for key, value in expected.items():
                if value and result[key] != value:
                    raise RootError(
                        f"ramdisk {key} mismatch: {result[key]} != {value}"
                    )
        return result


def board_partition_limit(source: Path) -> int:
    path = source / "device/nothing/asteroids/BoardConfig.mk"
    if not path.is_file():
        raise RootError(f"missing device tree file: {path}")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = BOARD_SIZE.match(line)
        if match:
            return int(match.group(1), 0)
    raise RootError(
        "BOARD_INIT_BOOT_IMAGE_PARTITION_SIZE is missing from "
        f"{path}"
    )


def load_state(path: Path, mode: str) -> dict[str, Any]:
    state = load_json(path / "root-state.json")
    if state.get("schema") != 1:
        raise RootError(f"unsupported root state schema in {path}")
    if state.get("mode") != mode:
        raise RootError(
            f"root state is for {state.get('mode')!r}, not {mode!r}; rerun root-prepare"
        )
    required = (
        "base_ota_sha256",
        "patched_init_boot_sha256",
        "source_init_boot_sha256",
        "stock_init_sha256",
        "ksuinit_sha256",
        "lkm_sha256",
        "manager_sha256",
        "patcher_sha256",
        "patched_init_boot_size",
        "partition_limit",
        "kmi",
    )
    missing = [key for key in required if key not in state]
    if missing:
        raise RootError(
            f"root state is incomplete ({', '.join(missing)}); rerun root-prepare"
        )
    for key in (
        "base_ota_sha256",
        "patched_init_boot_sha256",
        "source_init_boot_sha256",
        "stock_init_sha256",
        "ksuinit_sha256",
        "lkm_sha256",
        "manager_sha256",
    ):
        state[key] = require_hex(state.get(key), f"root state {key}")
    for key in ("manager_cert_sha256", "patcher_sha256"):
        if key in state:
            state[key] = require_hex(state.get(key), f"root state {key}")
    for key in ("patched_init_boot_size", "partition_limit"):
        value = state.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise RootError(f"root state {key} is not a positive integer")
    if "manager_cert_size" in state:
        value = state.get("manager_cert_size")
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise RootError("root state manager_cert_size is not a positive integer")
    if state["patched_init_boot_size"] > state["partition_limit"]:
        raise RootError("root state patched init_boot exceeds the partition limit")
    if not isinstance(state["kmi"], str) or not state["kmi"]:
        raise RootError("root state KMI is missing")
    return state


def state_path(state_dir: Path) -> Path:
    return state_dir / "root-state.json"


def command_prepare(args: argparse.Namespace) -> int:
    mode = args.mode
    if mode not in ROOT_MODES:
        raise RootError(f"root mode {mode!r} cannot be prepared")
    base_ota = Path(args.base_ota).expanduser()
    if not base_ota.is_file() or base_ota.stat().st_size == 0:
        raise RootError(f"missing base OTA: {base_ota}")
    source = Path(args.source).expanduser()
    state_dir = Path(args.state_dir).expanduser()
    cache_dir = Path(args.cache_dir).expanduser()
    avbroot = Path(args.avbroot).expanduser()
    avbroot_version = require_avbroot(avbroot)
    profiles, profile = load_profiles(Path(args.profiles), mode)
    kmi = profiles["kmi"]
    arch = profiles["arch"]
    patcher_asset = profiles["patcher"]
    if not isinstance(patcher_asset, dict):
        raise RootError("patcher profile is malformed")

    print(f"root mode: {profile.get('display_name', mode)}", file=sys.stderr)
    print(f"base OTA:  {base_ota}", file=sys.stderr)
    base_hash = sha256_file(base_ota)
    print(f"base SHA:  {base_hash}", file=sys.stderr)

    manager_asset = profile["manager"]
    lkm_asset = profile["lkm"]
    init_asset = profile["init"]
    lkm_hint = " ".join(
        str(lkm_asset.get(key, "")) for key in ("member", "name", "url")
    )
    embedded_lkm = lkm_asset.get("embedded")
    if isinstance(embedded_lkm, dict):
        lkm_hint += " " + str(embedded_lkm.get("member", ""))
    if kmi not in lkm_hint:
        raise RootError(f"{mode} LKM is not pinned for KMI {kmi}")
    patcher = download(
        patcher_asset["url"],
        cache_dir / asset_filename(patcher_asset),
        patcher_asset["sha256"],
        executable=True,
    )
    manager = download(
        manager_asset["url"],
        cache_dir / asset_filename(manager_asset),
        manager_asset["sha256"],
    )
    manager_size, manager_cert = verify_manager(manager, manager_asset)

    work = Path(tempfile.mkdtemp(prefix=".prepare.", dir=cache_dir))
    work.chmod(0o700)
    try:
        if isinstance(lkm_asset.get("embedded"), dict):
            lkm = extract_embedded_asset(
                manager, lkm_asset, work / "kernelsu.ko"
            )
        else:
            lkm_archive = download(
                lkm_asset["url"],
                cache_dir / asset_filename(lkm_asset),
                lkm_asset["sha256"],
            )
            lkm = (
                extract_member(
                    lkm_archive,
                    lkm_asset["member"],
                    work / "kernelsu.ko",
                    lkm_asset["member_sha256"],
                )
                if lkm_asset.get("member")
                else lkm_archive
            )
        if isinstance(init_asset.get("embedded"), dict):
            ksuinit = extract_embedded_asset(
                manager,
                init_asset,
                work / "ksuinit",
                executable=True,
            )
        else:
            init_archive = download(
                init_asset["url"],
                cache_dir / asset_filename(init_asset),
                init_asset["sha256"],
            )
            ksuinit = (
                extract_member(
                    init_archive,
                    init_asset["member"],
                    work / "ksuinit",
                    init_asset["member_sha256"],
                    executable=True,
                )
                if init_asset.get("member")
                else init_archive
            )
        if not lkm.is_file() or not ksuinit.is_file():
            raise RootError("could not resolve the LKM or ksuinit payload")
        lkm_hash = sha256_file(lkm)
        ksuinit_hash = sha256_file(ksuinit)

        stock = extract_init_boot(avbroot, base_ota, work / "ota")
        stock_info = inspect_ramdisk(avbroot, stock, "stock")
        stock_hash = sha256_file(stock)
        print(f"stock init_boot: {stock_hash}", file=sys.stderr)

        patched_dir = work / "patched"
        patched_dir.mkdir()
        command = [
            str(patcher),
            "boot-patch",
            "--boot",
            str(stock),
            "--kmi",
            str(kmi),
            "--arch",
            str(arch),
            "--init",
            str(ksuinit),
            "--module",
            str(lkm),
            "--out",
            str(patched_dir),
            "--out-name",
            "init_boot.img",
        ]
        run_checked(command)
        patched = patched_dir / "init_boot.img"
        if not patched.is_file() or patched.stat().st_size == 0:
            raise RootError("patcher produced no init_boot.img")
        patched_info = inspect_ramdisk(
            avbroot,
            patched,
            mode,
            {
                "ksuinit_sha256": ksuinit_hash,
                "stock_init_sha256": stock_info["init_sha256"],
                "lkm_sha256": lkm_hash,
            },
        )
        patched_hash = sha256_file(patched)
        if patched_hash == stock_hash:
            raise RootError("patched init_boot is byte-identical to the stock image")

        limit = board_partition_limit(source)
        patched_size = patched.stat().st_size
        if patched_size > limit:
            raise RootError(
                f"patched init_boot is too large: {patched_size} > {limit} bytes"
            )

        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        state_dir.chmod(0o700)
        shutil.copy2(patched, state_dir / "init_boot.img")
        shutil.copy2(manager, state_dir / "manager.apk")
        state = {
            "schema": 1,
            "mode": mode,
            "display_name": profile.get("display_name", mode),
            "source_commit": profile.get("source_commit"),
            "kmi": kmi,
            "arch": arch,
            "base_ota": str(base_ota),
            "base_ota_sha256": base_hash,
            "source_init_boot_sha256": stock_hash,
            "patched_init_boot_sha256": patched_hash,
            "patched_init_boot_size": patched_size,
            "partition_limit": limit,
            "stock_init_sha256": stock_info["init_sha256"],
            "ksuinit_sha256": patched_info["init_sha256"],
            "lkm_sha256": patched_info["lkm_sha256"],
            "manager_name": manager_asset["name"],
            "manager_sha256": require_hex(
                manager_asset["sha256"], "manager sha256"
            ),
            "manager_cert_sha256": manager_cert,
            "manager_cert_size": manager_size,
            "patcher_name": patcher_asset["name"],
            "patcher_file": asset_filename(patcher_asset),
            "patcher_sha256": require_hex(
                patcher_asset["sha256"], "patcher sha256"
            ),
            "avbroot_version": avbroot_version,
        }
        write_atomic(state_path(state_dir), json.dumps(state, indent=2).encode() + b"\n")
        write_text(
            state_dir / "source-init_boot.sha256", stock_hash + "\n", 0o600
        )
        write_text(
            state_dir / "source-ota.sha256", base_hash + "\n", 0o600
        )
        write_text(
            state_dir / "patched-init_boot.sha256", patched_hash + "\n", 0o600
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(f"prepared {mode} init_boot: {state_dir / 'init_boot.img'}")
    print(f"patched SHA-256: {patched_hash}")
    print(f"manager APK: {state_dir / 'manager.apk'}")
    print(f"base init_boot SHA-256: {stock_hash}")
    print("next: package the OTA with the same LENOS_ROOT value")
    return 0


def command_check_source(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).expanduser()
    base_ota = Path(args.base_ota).expanduser()
    avbroot = Path(args.avbroot).expanduser()
    state = load_state(state_dir, args.mode)
    if not base_ota.is_file() or base_ota.stat().st_size == 0:
        raise RootError(f"missing base OTA: {base_ota}")
    require_avbroot(avbroot)
    actual_ota = sha256_file(base_ota)
    if actual_ota != state["base_ota_sha256"]:
        raise RootError(
            "base OTA changed since root-prepare: "
            f"{actual_ota} != {state['base_ota_sha256']}"
        )
    with tempfile.TemporaryDirectory(prefix="lenos-root-source-") as temporary:
        image = extract_init_boot(avbroot, base_ota, Path(temporary) / "ota")
        actual_init = sha256_file(image)
        stock_info = inspect_ramdisk(avbroot, image, "stock")
    if actual_init != state["source_init_boot_sha256"]:
        raise RootError(
            "base OTA init_boot changed since root-prepare: "
            f"{actual_init} != {state['source_init_boot_sha256']}"
        )
    if stock_info["init_sha256"] != state["stock_init_sha256"]:
        raise RootError(
            "base OTA stock init changed since root-prepare: "
            f"{stock_info['init_sha256']} != {state['stock_init_sha256']}"
        )
    print(f"ok source OTA: {base_ota}")
    print(f"base_ota_sha256={actual_ota}")
    print(f"source_init_boot_sha256={actual_init}")
    return 0


def command_verify_image(args: argparse.Namespace) -> int:
    image = Path(args.image).expanduser()
    avbroot = Path(args.avbroot).expanduser()
    if not image.is_file() or image.stat().st_size == 0:
        raise RootError(f"missing image: {image}")
    require_avbroot(avbroot)
    state = None
    if args.mode != "stock":
        state = load_state(Path(args.state_dir).expanduser(), args.mode)
    info = inspect_ramdisk(avbroot, image, args.mode, state)
    print(f"ok {args.mode} ramdisk: {image}")
    for key in ("init_sha256", "init_real_sha256", "lkm_sha256"):
        if key in info:
            print(f"{key}={info[key]}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).expanduser()
    state = load_state(state_dir, args.mode)
    profiles, profile = load_profiles(Path(args.profiles), args.mode)
    if state["kmi"] != profiles["kmi"]:
        raise RootError(
            f"root state KMI {state['kmi']!r} does not match the pinned "
            f"{profiles['kmi']!r} profile"
        )
    pinned_payload = {
        "lkm_sha256": require_hex(
            profile["lkm"].get("member_sha256"), "pinned LKM member sha256"
        ),
        "ksuinit_sha256": require_hex(
            profile["init"].get("member_sha256"), "pinned ksuinit member sha256"
        ),
        "patcher_sha256": require_hex(
            profiles["patcher"].get("sha256"), "pinned patcher sha256"
        ),
    }
    for key, expected in pinned_payload.items():
        if state[key] != expected:
            raise RootError(
                f"root state {key} does not match the pinned {args.mode} profile"
            )
    image = state_dir / "init_boot.img"
    manager = state_dir / "manager.apk"
    if not image.is_file() or sha256_file(image) != state["patched_init_boot_sha256"]:
        raise RootError(f"root state image is missing or changed: {image}")
    if manager.is_file():
        manager_hash = sha256_file(manager)
    else:
        manager_hash = "missing"
    print(f"mode={state['mode']}")
    print(f"display_name={state.get('display_name', state['mode'])}")
    print(f"kmi={state['kmi']}")
    print(f"base_ota={state.get('base_ota', '')}")
    print(f"base_ota_sha256={state['base_ota_sha256']}")
    print(f"source_init_boot_sha256={state['source_init_boot_sha256']}")
    print(f"patched_init_boot_sha256={state['patched_init_boot_sha256']}")
    print(f"patched_init_boot_size={state['patched_init_boot_size']}")
    print(f"partition_limit={state['partition_limit']}")
    print(f"manager_name={state.get('manager_name', '')}")
    print(f"manager_sha256={manager_hash}")
    print(f"state_dir={state_dir}")
    if manager_hash == "missing":
        raise RootError(f"manager APK is missing: {manager}")
    manager_asset = profile["manager"]
    expected_manager = require_hex(manager_asset["sha256"], "manager sha256")
    if state["manager_sha256"] != expected_manager:
        raise RootError(
            f"root state manager hash does not match the pinned {args.mode} profile"
        )
    if manager_hash != expected_manager:
        raise RootError(
            f"manager APK does not match the pinned {args.mode} profile: {manager}"
        )
    cert_size, cert_hash = verify_manager(manager, manager_asset)
    if "manager_cert_sha256" in state and cert_hash != state["manager_cert_sha256"]:
        raise RootError("manager APK signer certificate changed")
    if "manager_cert_size" in state and cert_size != state["manager_cert_size"]:
        raise RootError("manager APK signer certificate size changed")
    print(f"manager_cert_sha256={cert_hash}")
    print(f"manager_cert_size={cert_size}")
    if args.avbroot:
        avbroot = Path(args.avbroot).expanduser()
        require_avbroot(avbroot)
        inspect_ramdisk(avbroot, image, args.mode, state)
        print("ramdisk=ok")
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="patch init_boot from a signed base OTA")
    prepare.add_argument("--mode", required=True, choices=("bakasu", "kernelsu"))
    prepare.add_argument("--base-ota", required=True)
    prepare.add_argument("--state-dir", required=True)
    prepare.add_argument("--cache-dir", required=True)
    prepare.add_argument("--source", required=True)
    prepare.add_argument("--avbroot", required=True)
    prepare.add_argument("--profiles", default=str(DEFAULT_PROFILES))
    prepare.set_defaults(func=command_prepare)

    source = sub.add_parser(
        "check-source", help="check the base OTA and init_boot against root state"
    )
    source.add_argument("--mode", required=True, choices=("bakasu", "kernelsu"))
    source.add_argument("--state-dir", required=True)
    source.add_argument("--base-ota", required=True)
    source.add_argument("--avbroot", required=True)
    source.set_defaults(func=command_check_source)

    verify = sub.add_parser("verify-image", help="verify a stock or patched init_boot")
    verify.add_argument("--mode", required=True, choices=("stock", "bakasu", "kernelsu"))
    verify.add_argument("--image", required=True)
    verify.add_argument("--state-dir", default="")
    verify.add_argument("--avbroot", required=True)
    verify.set_defaults(func=command_verify_image)

    status = sub.add_parser("status", help="print and check prepared root state")
    status.add_argument("--mode", required=True, choices=("bakasu", "kernelsu"))
    status.add_argument("--state-dir", required=True)
    status.add_argument("--avbroot", default="")
    status.add_argument("--profiles", default=str(DEFAULT_PROFILES))
    status.set_defaults(func=command_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.command == "verify-image" and args.mode != "stock" and not args.state_dir:
        print("error: --state-dir is required for a patched image", file=sys.stderr)
        return 2
    try:
        return int(args.func(args))
    except (RootError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
