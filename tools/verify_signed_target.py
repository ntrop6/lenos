#!/usr/bin/env python3
"""Verify actual APK/APEX container and APEX payload signers in target-files."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import ssl
import subprocess
import tempfile
import zipfile
from pathlib import Path

CERT_LINE = re.compile(r"certificate SHA-256 digest:\s*([0-9a-fA-F:]{64,95})")


class AuditError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cert_sha256(path: Path) -> str:
    try:
        der = ssl.PEM_cert_to_DER_cert(path.read_text(encoding="ascii"))
    except (OSError, ValueError) as exc:
        raise AuditError(f"cannot parse certificate {path}: {exc}") from exc
    if isinstance(der, str):
        der = base64.b64decode(der)
    return hashlib.sha256(der).hexdigest()


def run_apksigner(apksigner: Path, path: Path) -> set[str]:
    proc = subprocess.run(
        [str(apksigner), "verify", "--print-certs", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
    )
    if proc.returncode:
        raise AuditError(f"apksigner rejected {path.name}:\n{proc.stdout}")
    result = {
        match.group(1).replace(":", "").lower()
        for match in CERT_LINE.finditer(proc.stdout)
    }
    if not result:
        raise AuditError(f"apksigner returned no certificate digest for {path.name}")
    return result


# Only these top-level target-files trees become part of the flashed OS and are
# therefore covered by META/apkcerts.txt. A target-files zip built from a full
# `m` also carries TESTCASES/ (CTS/GTS harness APKs) and DATA/ (test payloads),
# which are never signed by sign_target_files_apks and never appear in
# apkcerts.txt. Auditing those made coverage look "unaccounted" even though the
# real OS partitions were signed correctly.
SIGNED_PARTITION_ROOTS = (
    "SYSTEM/",
    "SYSTEM_EXT/",
    "SYSTEM_DLKM/",
    "PRODUCT/",
    "VENDOR/",
    "VENDOR_DLKM/",
    "ODM/",
    "ODM_DLKM/",
    "RECOVERY/",
    "BOOT/",
    "VENDOR_BOOT/",
    "ROOT/",
)


def in_signed_partition(name: str) -> bool:
    return name.startswith(SIGNED_PARTITION_ROOTS)


def matching_entries(zf: zipfile.ZipFile, basename: str, *, apex: bool = False) -> list[str]:
    result = []
    capex = basename.removesuffix(".apex") + ".capex" if apex else ""
    for name in zf.namelist():
        if not in_signed_partition(name):
            continue
        current = name.rsplit("/", 1)[-1]
        if current == basename or (capex and current == capex):
            result.append(name)
    return sorted(result)


def package_inventory(zf: zipfile.ZipFile) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Enumerate every installed-partition APK/APEX artifact by normalized basename."""
    apks: dict[str, list[str]] = {}
    apexes: dict[str, list[str]] = {}
    seen_paths: set[str] = set()
    for info in zf.infolist():
        name = info.filename
        if info.is_dir():
            continue
        if name in seen_paths:
            raise AuditError(f"duplicate ZIP member: {name}")
        seen_paths.add(name)
        if not in_signed_partition(name):
            continue
        current = name.rsplit("/", 1)[-1]
        if current.endswith(".apk"):
            apks.setdefault(current, []).append(name)
        elif current.endswith(".apex"):
            apexes.setdefault(current, []).append(name)
        elif current.endswith(".capex"):
            normalized = current.removesuffix(".capex") + ".apex"
            apexes.setdefault(normalized, []).append(name)
    return (
        {key: sorted(value) for key, value in sorted(apks.items())},
        {key: sorted(value) for key, value in sorted(apexes.items())},
    )


def verify_inventory_coverage(
    original: zipfile.ZipFile, signed: zipfile.ZipFile, plan: dict
) -> None:
    expected_apks = {item["name"] for item in plan["apks"]} | set(plan["presigned_apks"])
    expected_apexes = {item["name"] for item in plan["apexes"]} | set(plan["presigned_apexes"])
    if len(expected_apks) != len(plan["apks"]) + len(plan["presigned_apks"]):
        raise AuditError("APK signing plan contains duplicate signable/presigned names")
    if len(expected_apexes) != len(plan["apexes"]) + len(plan["presigned_apexes"]):
        raise AuditError("APEX signing plan contains duplicate signable/presigned names")

    original_apks, original_apexes = package_inventory(original)
    signed_apks, signed_apexes = package_inventory(signed)
    # The signing plan is derived from META/apkcerts.txt, which on a full `m`
    # build enumerates every APK the build produced -- including CTS/GTS harness
    # APKs that never land in a flashed partition. Those plan entries having no
    # partition file is expected and harmless. The security-relevant direction is
    # the other one: every APK/APEX actually shipped inside a signed partition
    # must be accounted for by the plan, so nothing ships unsigned or unreviewed.
    unaccounted = sorted(set(original_apks) - expected_apks)
    if unaccounted:
        raise AuditError(
            f"APK entries in signed partitions are absent from the signing plan: {unaccounted}"
        )
    unaccounted = sorted(set(original_apexes) - expected_apexes)
    if unaccounted:
        raise AuditError(
            f"APEX entries in signed partitions are absent from the signing plan: {unaccounted}"
        )
    if original_apks != signed_apks:
        raise AuditError("signed target-files changed the complete APK entry inventory")
    if original_apexes != signed_apexes:
        raise AuditError("signed target-files changed the complete APEX entry inventory")


def unwrap_apex(data: bytes, name: str) -> bytes:
    if not name.endswith(".capex"):
        return data
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.read("original_apex")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise AuditError(f"malformed compressed APEX {name}: {exc}") from exc


def verify_apex_payload(avbtool: Path, apex_data: bytes, key: Path, temp: Path, label: str) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(apex_data)) as zf:
            payload = zf.read("apex_payload.img")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise AuditError(f"APEX {label} has no valid apex_payload.img: {exc}") from exc
    image = temp / (hashlib.sha256(label.encode()).hexdigest() + ".img")
    image.write_bytes(payload)
    proc = subprocess.run(
        [str(avbtool), "verify_image", "--image", str(image), "--key", str(key)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
    )
    image.unlink(missing_ok=True)
    if proc.returncode:
        raise AuditError(f"APEX payload key/content verification failed for {label}:\n{proc.stdout}")


def verify_unchanged(
    original: zipfile.ZipFile, signed: zipfile.ZipFile, basename: str, *, apex: bool = False
) -> int:
    before = matching_entries(original, basename, apex=apex)
    after = matching_entries(signed, basename, apex=apex)
    if not before and not after:
        return 0
    if not before or before != after:
        raise AuditError(f"presigned entry set changed for {basename}: {before} -> {after}")
    for name in before:
        if original.read(name) != signed.read(name):
            raise AuditError(f"presigned entry bytes changed: {name}")
    return len(before)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--signed", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--package-keys", required=True, type=Path)
    parser.add_argument("--apex-keys", required=True, type=Path)
    parser.add_argument("--apksigner", required=True, type=Path)
    parser.add_argument("--avbtool", required=True, type=Path)
    args = parser.parse_args()

    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        if plan.get("schema") != 2:
            raise AuditError("unsupported signing plan schema")
        if sha256_file(args.input) != plan.get("target_files_sha256"):
            raise AuditError("input target-files hash no longer matches the signing plan")
        if not args.apksigner.is_file() or not args.avbtool.is_file():
            raise AuditError("apksigner or avbtool executable is missing")

        apk_count = apex_count = payload_count = presigned_count = 0
        with zipfile.ZipFile(args.input) as original, zipfile.ZipFile(args.signed) as signed, \
                tempfile.TemporaryDirectory(prefix="lenos-signer-audit-") as td:
            temp = Path(td)
            verify_inventory_coverage(original, signed, plan)
            for item in plan["apks"]:
                name, key_id = item["name"], item["key_id"]
                expected = cert_sha256(args.package_keys / f"{key_id}.x509.pem")
                entries = matching_entries(signed, name)
                if not entries:
                    # Plan entry with no signed-partition file: a build-only
                    # (test/harness) APK listed in apkcerts.txt. Nothing ships.
                    continue
                for entry in entries:
                    path = temp / (hashlib.sha256(entry.encode()).hexdigest() + ".apk")
                    path.write_bytes(signed.read(entry))
                    actual = run_apksigner(args.apksigner, path)
                    if actual != {expected}:
                        raise AuditError(
                            f"APK signer mismatch for {entry}: expected {expected}, got {sorted(actual)}"
                        )
                    apk_count += 1

            for name in plan["presigned_apks"]:
                presigned_count += verify_unchanged(original, signed, name)

            for item in plan["apexes"]:
                name, key_id = item["name"], item["key_id"]
                expected = cert_sha256(args.apex_keys / f"{key_id}.x509.pem")
                entries = matching_entries(signed, name, apex=True)
                if not entries:
                    continue
                for entry in entries:
                    apex_data = unwrap_apex(signed.read(entry), entry)
                    path = temp / (hashlib.sha256(entry.encode()).hexdigest() + ".apex")
                    path.write_bytes(apex_data)
                    actual = run_apksigner(args.apksigner, path)
                    if actual != {expected}:
                        raise AuditError(
                            f"APEX container signer mismatch for {entry}: expected {expected}, got {sorted(actual)}"
                        )
                    verify_apex_payload(
                        args.avbtool,
                        apex_data,
                        args.apex_keys / f"{key_id}.pem",
                        temp,
                        entry,
                    )
                    apex_count += 1
                    payload_count += 1

            for name in plan["presigned_apexes"]:
                presigned_count += verify_unchanged(original, signed, name, apex=True)

        print(
            "signed-target audit passed: "
            f"{apk_count} APKs, {apex_count} APEX containers, "
            f"{payload_count} APEX payloads, {presigned_count} preserved entries"
        )
        return 0
    except (AuditError, KeyError, OSError, json.JSONDecodeError, zipfile.BadZipFile,
            subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
