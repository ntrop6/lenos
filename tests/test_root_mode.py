"""Checks for the opt-in root path.

These tests prove the repository still defaults to rootless, that the root mode
is a post-build init_boot transform, and that the packaging shell path uses
--prepatched with verification. They use fake avbroot/manager fixtures and do
not build, download, flash, or boot anything.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from harness import VENDOR

TOOLS = VENDOR / "tools"
DRIVER = VENDOR / "lenos-1.0-shizuku.sh"
ROOT_TOOL = TOOLS / "lenos_root.py"
ROOT_HELPER = TOOLS / "apk_signing_cert.py"
PROFILES = TOOLS / "root-managers.json"


def _lp(data: bytes) -> bytes:
    return struct.pack("<I", len(data)) + data


def make_fake_apk(path: Path, cert: bytes = b"test signer certificate") -> tuple[int, str]:
    """Write a minimal ZIP with an APK v2 signing block and return cert pins."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"fake manifest\n")
    data = bytearray(buffer.getvalue())
    eocd = data.rfind(b"PK\x05\x06")
    central_directory = struct.unpack_from("<I", data, eocd + 16)[0]
    digests = _lp(b"")
    certificates = _lp(cert)
    signed = _lp(digests) + _lp(certificates) + _lp(b"")
    signer = _lp(signed) + _lp(b"") + _lp(b"")
    v2 = _lp(_lp(signer))
    pair = struct.pack("<Q", 4 + len(v2)) + struct.pack("<I", 0x7109871A) + v2
    block_size = len(pair) + 24
    block = (
        struct.pack("<Q", block_size)
        + pair
        + struct.pack("<Q", block_size)
        + b"APK Sig Block 42"
    )
    data[central_directory:central_directory] = block
    new_eocd = data.rfind(b"PK\x05\x06")
    struct.pack_into("<I", data, new_eocd + 16, central_directory + len(block))
    path.write_bytes(data)
    return len(cert), hashlib.sha256(cert).hexdigest()


sys.path.insert(0, str(TOOLS))
import lenos_root  # noqa: E402
import sanitize_fastboot_info  # noqa: E402


class TestRootProfiles(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(PROFILES.read_text(encoding="utf-8"))

    def test_profiles_are_pinned_for_the_asteroids_kmi(self):
        self.assertEqual(self.data["schema"], 1)
        self.assertEqual(self.data["kmi"], "android15-6.6")
        self.assertEqual(self.data["arch"], "aarch64")
        self.assertIn("bakasu", self.data["profiles"])
        self.assertIn("kernelsu", self.data["profiles"])

    def test_every_asset_uses_a_full_sha256_and_a_real_url(self):
        self.assertRegex(self.data["patcher"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(self.data["patcher"]["url"].startswith("https://"))
        self.assertNotIn("nightly.link", self.data["patcher"]["url"])
        for name, profile in self.data["profiles"].items():
            manager = profile["manager"]
            self.assertRegex(manager["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(manager["url"].startswith("https://"), name)
            self.assertNotIn("nightly.link", manager["url"])
            for key in ("lkm", "init"):
                blob = profile[key]
                self.assertRegex(blob["sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(blob["member_sha256"], r"^[0-9a-f]{64}$")
                embedded = blob.get("embedded")
                if embedded is not None:
                    self.assertEqual(embedded["asset"], "manager")
                    self.assertRegex(embedded["sha256"], r"^[0-9a-f]{64}$")
                    self.assertIsInstance(embedded["offset"], int)
                    self.assertGreaterEqual(embedded["offset"], 0)
                    self.assertEqual(embedded["compression"], "raw-deflate")
                    self.assertNotIn("url", blob)
                else:
                    self.assertTrue(blob["url"].startswith("https://"), name)
                    self.assertNotIn("nightly.link", blob["url"])

    def test_manager_certificates_are_pinned(self):
        for name, profile in self.data["profiles"].items():
            manager = profile["manager"]
            self.assertIsInstance(manager["cert_size"], int)
            self.assertRegex(manager["cert_sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(manager["cert_size"] > 0, name)

    def test_expected_pins_have_not_drifted(self):
        self.assertNotIn("resukisu", self.data["profiles"])
        bakasu = self.data["profiles"]["bakasu"]
        self.assertEqual(
            bakasu["source_commit"],
            "239e1e8871b8fcd51a6e5b3002e0ba522fdd99fb",
        )
        self.assertEqual(
            bakasu["manager"]["sha256"],
            "25657bc449439687608fffa04b4b586de90fc405e3dc6217bd997fc71ba0a0a1",
        )
        self.assertEqual(
            bakasu["lkm"]["member_sha256"],
            "4241d4334d22b5824023c848086f803973b8af44f28032572bd1146cd938501d",
        )
        self.assertEqual(
            bakasu["init"]["member_sha256"],
            "761afc0cac6ad839685493246cb352fa70a51ac2898daad70d1e88bf394b6dde",
        )
        self.assertEqual(
            bakasu["lkm"]["embedded"]["sha256"],
            "c80b0cb7a5b240ea442a3963f2f0cfabde0b1cd197056772793064766ae9263a",
        )
        self.assertEqual(bakasu["lkm"]["embedded"]["offset"], 920170)
        self.assertEqual(bakasu["init"]["embedded"]["offset"], 2405158)
        kernelsu = self.data["profiles"]["kernelsu"]
        self.assertEqual(
            kernelsu["manager"]["sha256"],
            "b4a059ace71de2fa65cc7f12b1c58d55fc23ab25e057ee4230ce779742abe450",
        )
        self.assertEqual(
            kernelsu["lkm"]["member_sha256"],
            "e57ce23de951be6b0dee5030f6724322fed126aa4af71828994437bfb0bb61ad",
        )

    def test_patcher_is_the_host_binary(self):
        patcher = self.data["patcher"]
        self.assertIn("x86_64", patcher["name"])
        self.assertIn("ksud", patcher["name"])
        self.assertEqual(
            patcher["sha256"],
            "29b50f946a3cc40b04aef3dd587adad227fe0f70edf9c56b02c84479f0b0e954",
        )


class TestRootDriver(unittest.TestCase):
    def run_driver(self, *args: str, env: dict[str, str] | None = None):
        command_env = os.environ.copy()
        command_env.pop("LENOS_ROOT", None)
        command_env.update(env or {})
        return subprocess.run(
            [str(DRIVER), *args],
            cwd=str(VENDOR),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=command_env,
        )

    def test_default_flash_plan_is_rootless(self):
        result = self.run_driver("flash-plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ROOTLESS", result.stdout)
        self.assertNotIn("manager.apk", result.stdout)

    def test_bakasu_flash_plan_is_mode_aware(self):
        result = self.run_driver(
            "flash-plan", env={"LENOS_ROOT": "bakasu"}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ROOT (bakasu)", result.stdout)
        self.assertIn("lenos-asteroids-bakasu-manager.apk", result.stdout)
        self.assertIn("extracted-bakasu", result.stdout)
        self.assertIn('scp "build-host:', result.stdout)
        self.assertNotIn("ROOTLESS", result.stdout)

    def test_cli_root_flag_matches_environment(self):
        result = self.run_driver("--root", "kernelsu", "flash-plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ROOT (kernelsu)", result.stdout)

    def test_empty_cli_root_is_rejected(self):
        result = self.run_driver("--root=", "package")
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid LENOS_ROOT", result.stderr)

    def test_unknown_root_mode_is_rejected_before_anything_runs(self):
        result = self.run_driver(
            "package", env={"LENOS_ROOT": "magisk"}
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid LENOS_ROOT", result.stderr)

    def test_lock_gates_always_refuse(self):
        rootless = self.run_driver("lock-gates")
        self.assertEqual(rootless.returncode, 1)
        self.assertIn("refusing to print a lock sequence", rootless.stdout)
        self.assertNotIn("fastboot flashing lock", rootless.stdout)
        self.assertNotIn("avb_custom_key", rootless.stdout)
        for mode in ("bakasu", "kernelsu"):
            result = self.run_driver("lock-gates", env={"LENOS_ROOT": mode})
            self.assertEqual(result.returncode, 1)
            self.assertIn("will not run", result.stdout)
            self.assertIn("REFERENCE ONLY", result.stdout)
            self.assertIn("does not install or verify", result.stdout)
            self.assertNotIn("fastboot erase", result.stdout)
            self.assertNotIn("fastboot flash", result.stdout)
            self.assertNotIn("fastboot flashing lock", result.stdout)

    def test_root_packaging_uses_prepatched_and_requires_init_boot(self):
        text = DRIVER.read_text(encoding="utf-8")
        self.assertIn('ROOT_MODE="none"', text)
        self.assertIn('args+=(--prepatched "$ROOT_STATE_DIR/init_boot.img")', text)
        self.assertIn(
            "for required in init_boot boot vendor_boot vbmeta", text
        )
        self.assertIn(
            'need_file "$WS/lenos-asteroids-$ROOT_MODE-manager.apk"', text
        )
        self.assertIn('parts_text="$(collect_os_resign)"', text)
        self.assertIn("check-source", text)
        self.assertIn("root-prepare", text)
        self.assertIn("root-status", text)

    def test_rootless_package_uses_rootless_and_not_prepatched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ws = root / "workspace"
            src = root / "source"
            keys = root / "keys"
            for path in (ws, keys, src / "device/nothing/asteroids"):
                path.mkdir(parents=True)
            (src / "device/nothing/asteroids/lineage_asteroids.mk").write_text(
                "x\n", encoding="utf-8"
            )
            (src / "device/nothing/asteroids/BoardConfig.mk").write_text(
                "BOARD_INIT_BOOT_IMAGE_PARTITION_SIZE := 0x800000\n",
                encoding="utf-8",
            )
            base = root / "base.zip"
            base.write_bytes(b"base OTA bytes")
            (ws / "signing-plan.json").write_text(
                json.dumps(
                    {
                        "resign_partitions": [
                            "boot",
                            "init_boot",
                            "vendor_boot",
                            "vbmeta",
                        ]
                    }
                ),
                encoding="utf-8",
            )
            for name in ("avb.key", "ota.key", "ota.crt", "avb_pkmd.bin"):
                (keys / name).write_text("test key material\n", encoding="utf-8")
            wizard = root / "fake-wizard.sh"
            wizard.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            wizard.chmod(0o755)
            log = root / "avbroot.log"
            fake = root / "avbroot"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'printf \'%s\\n\' "$*" >> "${FAKE_AVBROOT_LOG:?}"\n'
                'if [[ "${1:-}" == "--version" ]]; then\n'
                '  echo "avbroot 3.33.0"\n'
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "boot" && "${2:-}" == "unpack" '
                '&& "${3:-}" == "--help" ]]; then\n'
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "cpio" && "${2:-}" == "unpack" '
                '&& "${3:-}" == "--help" ]]; then\n'
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "boot" && "${2:-}" == "unpack" ]]; then\n'
                '  printf "fake ramdisk\\n" > ramdisk.img.0\n'
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "cpio" && "${2:-}" == "unpack" ]]; then\n'
                '  info=""\n'
                '  tree=""\n'
                "  shift 2\n"
                "  while (($#)); do\n"
                '    case "$1" in\n'
                '      --output-info) info="$2"; shift 2;;\n'
                '      --output-tree) tree="$2"; shift 2;;\n'
                "      *) shift;;\n"
                "    esac\n"
                "  done\n"
                '  [[ -n "$info" && -n "$tree" ]] || exit 2\n'
                '  mkdir -p "$tree"\n'
                '  printf "stock init\\n" > "$tree/init"\n'
                '  chmod 755 "$tree/init"\n'
                '  cat > "$info" <<\'EOF\'\n'
                "[[entries]]\n"
                'path = "init"\n'
                'file_type = "Regular"\n'
                'file_mode = "755"\n'
                "EOF\n"
                '  if [[ "${FAKE_RAMDISK_MODE:-stock}" == "patched" ]]; then\n'
                '    printf "patched init\\n" > "$tree/init"\n'
                '    printf "stock init\\n" > "$tree/init.real"\n'
                '    printf "fake ko\\n" > "$tree/kernelsu.ko"\n'
                '    chmod 755 "$tree/init.real"\n'
                '    cat >> "$info" <<\'EOF\'\n'
                "\n[[entries]]\n"
                'path = "init.real"\n'
                'file_type = "Regular"\n'
                'file_mode = "755"\n'
                "\n[[entries]]\n"
                'path = "kernelsu.ko"\n'
                'file_type = "Regular"\n'
                'file_mode = "644"\n'
                "EOF\n"
                "  fi\n"
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "ota" && "${2:-}" == "patch" ]]; then\n'
                '  out=""\n'
                "  saw_rootless=0\n"
                "  shift 2\n"
                "  while (($#)); do\n"
                "    case \"$1\" in\n"
                '      --output) out="$2"; shift 2;;\n'
                '      --rootless) saw_rootless=1; shift;;\n'
                '      --prepatched) echo "unexpected --prepatched" >&2; exit 2;;\n'
                "      *) shift;;\n"
                "    esac\n"
                "  done\n"
                '  [[ -n "$out" ]] || exit 2\n'
                '  [[ "$saw_rootless" -eq 1 ]] || { echo "missing --rootless" >&2; exit 2; }\n'
                '  printf "fake patched OTA\\n" > "$out"\n'
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "ota" && "${2:-}" == "verify" ]]; then\n'
                '  if [[ "${FAKE_VERIFY_FAIL:-0}" == "1" ]]; then\n'
                '    echo "fake bad signature" >&2\n'
                "    exit 1\n"
                "  fi\n"
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "ota" && "${2:-}" == "extract" ]]; then\n'
                '  dir=""\n'
                "  shift 2\n"
                "  while (($#)); do\n"
                "    case \"$1\" in\n"
                '      --directory) dir="$2"; shift 2;;\n'
                "      *) shift;;\n"
                "    esac\n"
                "  done\n"
                '  [[ -n "$dir" ]] || exit 2\n'
                '  mkdir -p "$dir"\n'
                '  printf "boot\\n" > "$dir/boot.img"\n'
                '  printf "init_boot\\n" > "$dir/init_boot.img"\n'
                '  printf "vendor_boot\\n" > "$dir/vendor_boot.img"\n'
                "  exit 0\n"
                "fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            result = self.run_driver(
                "package",
                env={
                    "LENOS_WORKSPACE": str(ws),
                    "LENOS_SOURCE": str(src),
                    "LENOS_KEYDIR": str(keys),
                    "LENOS_WIZARD": str(wizard),
                    "LENOS_WIZARD_SHA256": hashlib.sha256(
                        wizard.read_bytes()
                    ).hexdigest(),
                    "LENOS_BASE_OTA": str(base),
                    "AVBROOT": str(fake),
                    "FAKE_AVBROOT_LOG": str(log),
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            log_text = log.read_text(encoding="utf-8")
            self.assertIn("--rootless", log_text)
            self.assertNotIn("--prepatched", log_text)
            # The stock ramdisk verifier is the only caller of boot/cpio unpack.
            self.assertIn("boot unpack", log_text)
            self.assertIn("cpio unpack", log_text)
            self.assertTrue((ws / "lenos-asteroids-rootless.zip").is_file())

            # --rootless does not remove a root payload already in the base.
            result = self.run_driver(
                "package",
                env={
                    "LENOS_WORKSPACE": str(ws),
                    "LENOS_SOURCE": str(src),
                    "LENOS_KEYDIR": str(keys),
                    "LENOS_WIZARD": str(wizard),
                    "LENOS_WIZARD_SHA256": hashlib.sha256(
                        wizard.read_bytes()
                    ).hexdigest(),
                    "LENOS_BASE_OTA": str(base),
                    "AVBROOT": str(fake),
                    "FAKE_AVBROOT_LOG": str(log),
                    "FAKE_RAMDISK_MODE": "patched",
                },
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("not stock/rootless", result.stderr)

            # A base signed by a different key must fail before ota patch runs.
            patch_calls = log.read_text(encoding="utf-8").count("ota patch")
            result = self.run_driver(
                "package",
                env={
                    "LENOS_WORKSPACE": str(ws),
                    "LENOS_SOURCE": str(src),
                    "LENOS_KEYDIR": str(keys),
                    "LENOS_WIZARD": str(wizard),
                    "LENOS_WIZARD_SHA256": hashlib.sha256(
                        wizard.read_bytes()
                    ).hexdigest(),
                    "LENOS_BASE_OTA": str(base),
                    "AVBROOT": str(fake),
                    "FAKE_AVBROOT_LOG": str(log),
                    "FAKE_VERIFY_FAIL": "1",
                },
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("input OTA is not signed", result.stderr)
            self.assertEqual(
                log.read_text(encoding="utf-8").count("ota patch"), patch_calls
            )

    def test_root_package_uses_prepatched_and_verifies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ws = root / "workspace"
            src = root / "source"
            keys = root / "keys"
            vendor = root / "vendor"
            for path in (ws, keys, vendor / "tools", src / "device/nothing/asteroids"):
                path.mkdir(parents=True)
            (src / "device/nothing/asteroids/lineage_asteroids.mk").write_text(
                "x\n", encoding="utf-8"
            )
            (src / "device/nothing/asteroids/BoardConfig.mk").write_text(
                "BOARD_INIT_BOOT_IMAGE_PARTITION_SIZE := 0x800000\n",
                encoding="utf-8",
            )
            for name in ("lenos-patch.py", "lenos_projects.py", "apk_signing_cert.py"):
                shutil.copy2(TOOLS / name, vendor / "tools" / name)
            for name in ("firmware-deny.txt", "root-managers.json"):
                shutil.copy2(TOOLS / name, vendor / "tools" / name)
            stub_log = root / "lenos-root.log"
            stub = vendor / "tools/lenos_root.py"
            stub.write_text(
                "#!/usr/bin/env python3\n"
                "import os, sys\n"
                'with open(os.environ["FAKE_ROOT_LOG"], "a") as f:\n'
                '    f.write(" ".join(sys.argv[1:]) + "\\n")\n'
                "raise SystemExit(0)\n",
                encoding="utf-8",
            )
            base = root / "base.zip"
            base.write_bytes(b"base OTA bytes")
            (ws / "signing-plan.json").write_text(
                json.dumps(
                    {
                        "resign_partitions": [
                            "boot",
                            "init_boot",
                            "vendor_boot",
                            "vbmeta",
                        ]
                    }
                ),
                encoding="utf-8",
            )
            for name in ("avb.key", "ota.key", "ota.crt", "avb_pkmd.bin"):
                (keys / name).write_text("test key material\n", encoding="utf-8")
            wizard = root / "fake-wizard.sh"
            wizard.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            wizard.chmod(0o755)
            state = ws / "lenos-root/bakasu"
            state.mkdir(parents=True)
            (state / "init_boot.img").write_bytes(b"state init")
            (state / "manager.apk").write_bytes(b"manager")
            (state / "root-state.json").write_text("{}\n", encoding="utf-8")
            log = root / "avbroot.log"
            fake = root / "avbroot"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'printf \'%s\\n\' "$*" >> "${FAKE_AVBROOT_LOG:?}"\n'
                'if [[ "${1:-}" == "--version" ]]; then\n'
                '  echo "avbroot 3.33.0"\n'
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "boot" && "${2:-}" == "unpack" '
                '&& "${3:-}" == "--help" ]]; then exit 0; fi\n'
                'if [[ "${1:-}" == "cpio" && "${2:-}" == "unpack" '
                '&& "${3:-}" == "--help" ]]; then exit 0; fi\n'
                'if [[ "${1:-}" == "ota" && "${2:-}" == "verify" ]]; then exit 0; fi\n'
                'if [[ "${1:-}" == "ota" && "${2:-}" == "patch" ]]; then\n'
                '  out=""\n'
                "  saw_prepatched=0\n"
                "  shift 2\n"
                "  while (($#)); do\n"
                '    case "$1" in\n'
                '      --output) out="$2"; shift 2;;\n'
                '      --prepatched) saw_prepatched=1; shift 2;;\n'
                '      --rootless) echo "unexpected --rootless" >&2; exit 2;;\n'
                "      *) shift;;\n"
                "    esac\n"
                "  done\n"
                '  [[ -n "$out" && "$saw_prepatched" -eq 1 ]] || exit 2\n'
                '  printf "fake root OTA\\n" > "$out"\n'
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "ota" && "${2:-}" == "extract" ]]; then\n'
                '  dir=""\n'
                "  shift 2\n"
                "  while (($#)); do\n"
                '    case "$1" in\n'
                '      --directory) dir="$2"; shift 2;;\n'
                "      *) shift;;\n"
                "    esac\n"
                "  done\n"
                '  [[ -n "$dir" ]] || exit 2\n'
                '  mkdir -p "$dir"\n'
                '  printf "boot\\n" > "$dir/boot.img"\n'
                '  printf "init_boot\\n" > "$dir/init_boot.img"\n'
                '  printf "vendor_boot\\n" > "$dir/vendor_boot.img"\n'
                "  exit 0\n"
                "fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            result = self.run_driver(
                "package",
                env={
                    "LENOS_ROOT": "bakasu",
                    "LENOS_WORKSPACE": str(ws),
                    "LENOS_SOURCE": str(src),
                    "LENOS_KEYDIR": str(keys),
                    "LENOS_WIZARD": str(wizard),
                    "LENOS_WIZARD_SHA256": hashlib.sha256(
                        wizard.read_bytes()
                    ).hexdigest(),
                    "LENOS_VENDOR": str(vendor),
                    "LENOS_BASE_OTA": str(base),
                    "AVBROOT": str(fake),
                    "FAKE_AVBROOT_LOG": str(log),
                    "FAKE_ROOT_LOG": str(stub_log),
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            avb = log.read_text(encoding="utf-8")
            self.assertIn("--prepatched", avb)
            self.assertNotIn("--rootless", avb)
            self.assertIn("ota verify", avb)
            calls = stub_log.read_text(encoding="utf-8")
            self.assertIn("check-source", calls)
            self.assertIn("status", calls)
            self.assertIn("verify-image", calls)
            self.assertTrue((ws / "lenos-asteroids-bakasu.zip").is_file())
            self.assertTrue((ws / "lenos-asteroids-bakasu-manager.apk").is_file())

    def test_doctor_hash_pins_the_external_wizard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src = root / "src"
            (src / "device/nothing/asteroids").mkdir(parents=True)
            (src / "device/nothing/asteroids/lineage_asteroids.mk").write_text(
                "# fake device tree\n", encoding="utf-8"
            )
            keys = root / "keys"
            keys.mkdir()
            for name in ("avb.key", "ota.key", "ota.crt", "avb_pkmd.bin"):
                (keys / name).write_text("test key material\n", encoding="utf-8")
            avbroot = root / "avbroot"
            avbroot.write_text("#!/bin/sh\necho 'avbroot 3.33.0'\n", encoding="utf-8")
            avbroot.chmod(0o755)
            wizard = root / "fake-wizard.sh"
            wizard.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            wizard.chmod(0o755)
            env = {
                "LENOS_WORKSPACE": str(root / "ws"),
                "LENOS_SOURCE": str(src),
                "LENOS_KEYDIR": str(keys),
                "LENOS_WIZARD": str(wizard),
                    "LENOS_WIZARD_SHA256": hashlib.sha256(
                        wizard.read_bytes()
                    ).hexdigest(),
                "LENOS_VENDOR": str(VENDOR),
                "AVBROOT": str(avbroot),
            }
            wrong = self.run_driver(
                "doctor", env={**env, "LENOS_WIZARD_SHA256": "0" * 64}
            )
            self.assertEqual(wrong.returncode, 1)
            self.assertIn("external wizard hash mismatch", wrong.stderr)
            digest = hashlib.sha256(wizard.read_bytes()).hexdigest()
            right = self.run_driver(
                "doctor", env={**env, "LENOS_WIZARD_SHA256": digest}
            )
            self.assertEqual(right.returncode, 0, right.stderr)
            self.assertIn(digest, right.stderr)

    def test_root_prepare_never_talks_to_a_device(self):
        body = ROOT_TOOL.read_text(encoding="utf-8")
        self.assertNotRegex(body, r'["\']adb["\']')
        self.assertNotRegex(body, r'["\']fastboot["\']')
        self.assertNotIn("flashing lock", body)

    def test_root_tool_is_executable_and_has_help(self):
        self.assertTrue(os.access(ROOT_TOOL, os.X_OK))
        self.assertTrue(os.access(ROOT_HELPER, os.X_OK))
        result = subprocess.run(
            [sys.executable, str(ROOT_TOOL), "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("prepare", result.stdout)
        self.assertIn("check-source", result.stdout)
        self.assertIn("verify-image", result.stdout)


class TestRootHelpers(unittest.TestCase):
    def test_prepare_refuses_the_pinned_gki_lkm_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.zip"
            base.write_bytes(b"fake base OTA")
            avbroot = root / "avbroot"
            avbroot.write_text("#!/bin/sh\necho 'avbroot 3.33.0'\n", encoding="utf-8")
            avbroot.chmod(0o755)
            args = argparse.Namespace(
                mode="bakasu",
                base_ota=str(base),
                state_dir=str(root / "state"),
                cache_dir=str(root / "cache"),
                source=str(root),
                avbroot=str(avbroot),
                profiles=str(PROFILES),
                lkm="",
                allow_unvalidated_lkm=False,
            )
            with self.assertRaises(lenos_root.RootError) as caught:
                lenos_root.command_prepare(args)
            message = str(caught.exception)
            self.assertIn("pinned kernel module", message)
            self.assertIn("--lkm", message)
            self.assertIn("--allow-unvalidated-lkm", message)
            self.assertFalse((root / "cache").exists(), "must fail before downloads")

    def test_cpio_parser_reads_modes_and_duplicate_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            info = Path(directory) / "cpio.toml"
            info.write_text(
                "format = \"Lz4Legacy\"\n"
                "\n[[entries]]\n"
                "path = \"init\"\n"
                "file_type = \"Regular\"\n"
                "file_mode = \"755\"\n"
                "\n[[entries]]\n"
                "path = \"init.real\"\n"
                "file_type = \"Regular\"\n"
                "file_mode = \"750\"\n",
                encoding="utf-8",
            )
            entries = lenos_root.parse_cpio_info(info)
        self.assertEqual(entries["init"]["file_mode"], "755")
        self.assertTrue(lenos_root._is_executable(entries["init"]))
        self.assertTrue(lenos_root._is_executable(entries["init.real"]))
        self.assertFalse(lenos_root._is_executable({"file_mode": "644"}))

    def test_partition_limit_comes_from_the_device_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            board = source / "device/nothing/asteroids/BoardConfig.mk"
            board.parent.mkdir(parents=True)
            board.write_text(
                "BOARD_INIT_BOOT_IMAGE_PARTITION_SIZE := 0x800000\n",
                encoding="utf-8",
            )
            self.assertEqual(lenos_root.board_partition_limit(source), 8 * 1024 * 1024)

    def test_embedded_raw_deflate_payload_is_extracted_and_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"\x7fELF" + b"fake BakaSU payload\n"
            compressor = zlib.compressobj(level=9, wbits=-15)
            compressed = compressor.compress(payload) + compressor.flush()
            prefix = b"BakaSU embedded ksud\n"
            blob = prefix + compressed
            manager = root / "manager.apk"
            with zipfile.ZipFile(manager, "w") as archive:
                archive.writestr("lib/arm64-v8a/libksud.so", blob)
            digest = hashlib.sha256(payload).hexdigest()
            asset = {
                "name": "android15-6.6_kernelsu.ko",
                "sha256": digest,
                "member_sha256": digest,
                "embedded": {
                    "asset": "manager",
                    "member": "lib/arm64-v8a/libksud.so",
                    "sha256": hashlib.sha256(blob).hexdigest(),
                    "offset": len(prefix),
                    "compression": "raw-deflate",
                },
            }
            output = root / "kernelsu.ko"
            lenos_root.extract_embedded_asset(manager, asset, output)
            self.assertEqual(output.read_bytes(), payload)
            self.assertEqual(output.stat().st_mode & 0o777, 0o644)

            executable = root / "ksuinit"
            lenos_root.extract_embedded_asset(
                manager, asset, executable, executable=True
            )
            self.assertEqual(executable.read_bytes(), payload)
            self.assertEqual(executable.stat().st_mode & 0o777, 0o755)

            asset["member_sha256"] = "0" * 64
            with self.assertRaises(lenos_root.RootError):
                lenos_root.extract_embedded_asset(manager, asset, output)

    def test_incomplete_root_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            (state_dir / "root-state.json").write_text(
                '{"schema": 1, "mode": "bakasu"}\n', encoding="utf-8"
            )
            with self.assertRaises(lenos_root.RootError):
                lenos_root.load_state(state_dir, "bakasu")

    def test_root_state_rejects_malformed_hashes_and_oversized_images(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            state = {
                "schema": 1,
                "mode": "bakasu",
                "kmi": "android15-6.6",
                "base_ota_sha256": "a" * 64,
                "patched_init_boot_sha256": "b" * 64,
                "source_init_boot_sha256": "c" * 64,
                "stock_init_sha256": "d" * 64,
                "ksuinit_sha256": "e" * 64,
                "lkm_sha256": "f" * 64,
                "manager_sha256": "0" * 64,
                "patcher_sha256": "9" * 64,
                "patched_init_boot_size": 1,
                "partition_limit": 2,
            }
            state_file = state_dir / "root-state.json"
            state["patched_init_boot_size"] = 3
            state_file.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(lenos_root.RootError):
                lenos_root.load_state(state_dir, "bakasu")
            state["patched_init_boot_size"] = 1
            state["manager_sha256"] = "not-a-hash"
            state_file.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(lenos_root.RootError):
                lenos_root.load_state(state_dir, "bakasu")

    def test_check_source_binds_state_to_ota_and_init_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.zip"
            base.write_bytes(b"base OTA bytes")
            init = root / "init_boot.img"
            init.write_bytes(b"stock init_boot bytes")
            state_dir = root / "state"
            state_dir.mkdir()
            state = {
                "schema": 1,
                "mode": "bakasu",
                "kmi": "android15-6.6",
                "base_ota_sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
                "source_init_boot_sha256": hashlib.sha256(
                    init.read_bytes()
                ).hexdigest(),
                "patched_init_boot_sha256": "1" * 64,
                "stock_init_sha256": hashlib.sha256(b"stock init\n").hexdigest(),
                "ksuinit_sha256": "3" * 64,
                "lkm_sha256": "4" * 64,
                "manager_sha256": "5" * 64,
                "patcher_sha256": "6" * 64,
                "patched_init_boot_size": 1,
                "partition_limit": 2,
            }
            (state_dir / "root-state.json").write_text(
                json.dumps(state), encoding="utf-8"
            )
            fake = root / "avbroot"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                'if [[ "${1:-}" == "--version" ]]; then\n'
                '  echo "avbroot 3.33.0"\n'
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "boot" && "${2:-}" == "unpack" '
                '&& "${3:-}" == "--help" ]]; then\n'
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "cpio" && "${2:-}" == "unpack" '
                '&& "${3:-}" == "--help" ]]; then\n'
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "boot" && "${2:-}" == "unpack" ]]; then\n'
                '  printf "fake ramdisk\\n" > ramdisk.img.0\n'
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "cpio" && "${2:-}" == "unpack" ]]; then\n'
                '  info=""\n'
                '  tree=""\n'
                "  shift 2\n"
                "  while (($#)); do\n"
                '    case "$1" in\n'
                '      --output-info) info="$2"; shift 2;;\n'
                '      --output-tree) tree="$2"; shift 2;;\n'
                "      *) shift;;\n"
                "    esac\n"
                "  done\n"
                '  [[ -n "$info" && -n "$tree" ]] || exit 2\n'
                '  mkdir -p "$tree"\n'
                '  printf "stock init\\n" > "$tree/init"\n'
                '  chmod 755 "$tree/init"\n'
                '  printf "[[entries]]\\npath = \\"init\\"\\n'
                'file_type = \\"Regular\\"\\nfile_mode = \\"755\\"\\n" > "$info"\n'
                "  exit 0\n"
                "fi\n"
                'if [[ "${1:-}" == "ota" && "${2:-}" == "extract" ]]; then\n'
                '  dir=""\n'
                '  while (($#)); do\n'
                '    case "$1" in\n'
                '      --directory) dir="$2"; shift 2;;\n'
                '      *) shift;;\n'
                "    esac\n"
                "  done\n"
                '  [[ -n "$dir" ]] || exit 1\n'
                '  mkdir -p "$dir"\n'
                f"  cp {shlex.quote(str(init))} \"$dir/init_boot.img\"\n"
                "  exit 0\n"
                "fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            command = [
                sys.executable,
                str(ROOT_TOOL),
                "check-source",
                "--mode",
                "bakasu",
                "--state-dir",
                str(state_dir),
                "--base-ota",
                str(base),
                "--avbroot",
                str(fake),
            ]
            result = subprocess.run(
                command, text=True, capture_output=True, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ok source OTA", result.stdout)
            self.assertIn("source_init_boot_sha256=", result.stdout)

            base.write_bytes(b"different base OTA bytes")
            result = subprocess.run(
                command, text=True, capture_output=True, check=False
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("base OTA changed since root-prepare", result.stderr)

            base.write_bytes(b"base OTA bytes")
            state["stock_init_sha256"] = "0" * 64
            (state_dir / "root-state.json").write_text(
                json.dumps(state), encoding="utf-8"
            )
            result = subprocess.run(
                command, text=True, capture_output=True, check=False
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("stock init changed since root-prepare", result.stderr)

    def test_fake_apk_cert_pin_and_status_profile_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_dir = root / "state"
            state_dir.mkdir()
            image = state_dir / "init_boot.img"
            image.write_bytes(b"state init")
            manager = state_dir / "manager.apk"
            cert_size, cert_hash = make_fake_apk(manager)
            manager_hash = hashlib.sha256(manager.read_bytes()).hexdigest()
            ko_hash = hashlib.sha256(b"fake ko").hexdigest()
            init_hash = hashlib.sha256(b"patched init").hexdigest()

            profiles = json.loads(PROFILES.read_text(encoding="utf-8"))
            profile = profiles["profiles"]["bakasu"]
            profile["manager"].update(
                {
                    "sha256": manager_hash,
                    "cert_size": cert_size,
                    "cert_sha256": cert_hash,
                }
            )
            profile["lkm"]["sha256"] = ko_hash
            profile["lkm"]["member_sha256"] = ko_hash
            profile["init"]["sha256"] = init_hash
            profile["init"]["member_sha256"] = init_hash
            profile_file = root / "profiles.json"
            profile_file.write_text(json.dumps(profiles), encoding="utf-8")

            state = {
                "schema": 1,
                "mode": "bakasu",
                "kmi": profiles["kmi"],
                "base_ota_sha256": "a" * 64,
                "patched_init_boot_sha256": hashlib.sha256(
                    image.read_bytes()
                ).hexdigest(),
                "source_init_boot_sha256": "b" * 64,
                "stock_init_sha256": "c" * 64,
                "ksuinit_sha256": init_hash,
                "lkm_sha256": ko_hash,
                "manager_sha256": manager_hash,
                "manager_cert_sha256": cert_hash,
                "manager_cert_size": cert_size,
                "patcher_sha256": profiles["patcher"]["sha256"],
                "patched_init_boot_size": len(image.read_bytes()),
                "partition_limit": 1024,
            }
            state_file = state_dir / "root-state.json"
            state_file.write_text(json.dumps(state), encoding="utf-8")
            args = argparse.Namespace(
                mode="bakasu",
                state_dir=str(state_dir),
                avbroot="",
                profiles=str(profile_file),
            )
            with contextlib.redirect_stdout(io.StringIO()):
                lenos_root.command_status(args)
            state["lkm_sha256"] = "0" * 64
            state_file.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(lenos_root.RootError), contextlib.redirect_stdout(
                io.StringIO()
            ):
                lenos_root.command_status(args)

    def test_apk_signer_rejects_non_apk_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-an.apk"
            path.write_bytes(b"not a zip")
            result = subprocess.run(
                [sys.executable, str(ROOT_HELPER), str(path)],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("error:", result.stderr)


class TestFastbootSanitizer(unittest.TestCase):
    def test_every_pinned_firmware_partition_is_commented(self):
        firmware = sanitize_fastboot_info.load_deny(TOOLS / "firmware-deny.txt")
        with tempfile.TemporaryDirectory() as directory:
            info = Path(directory) / "fastboot-info.txt"
            names = sorted(firmware)
            info.write_text(
                "\n".join(
                    [f"flash {name}" for name in names]
                    + ["flash system", "flash vbmeta", "update-super", "reboot fastboot"]
                )
                + "\n",
                encoding="utf-8",
            )
            saw_reboot, saw_logical = sanitize_fastboot_info.sanitize(info, firmware)
            text = info.read_text(encoding="utf-8")
        self.assertTrue(saw_reboot)
        self.assertTrue(saw_logical)
        for name in names:
            self.assertNotIn(f"\nflash {name}\n", "\n" + text)
            self.assertIn(f"# flash {name}", text)
        self.assertIn("\nflash system\n", "\n" + text)
        self.assertIn("\nupdate-super\n", "\n" + text)
        self.assertLess(text.index("flash system"), text.index("flash vbmeta"))

    def test_vbmeta_is_after_every_logical_partition(self):
        firmware = sanitize_fastboot_info.load_deny(TOOLS / "firmware-deny.txt")
        with tempfile.TemporaryDirectory() as directory:
            info = Path(directory) / "fastboot-info.txt"
            info.write_text(
                "flash boot\n"
                "flash system\n"
                "flash vbmeta\n"
                "flash product\n"
                "flash vbmeta_system\n"
                "update-super\n"
                "reboot fastboot\n",
                encoding="utf-8",
            )
            sanitize_fastboot_info.sanitize(info, firmware)
            text = info.read_text(encoding="utf-8")
        self.assertLess(text.index("flash system"), text.index("flash vbmeta"))
        self.assertLess(text.index("flash product"), text.index("flash vbmeta"))
        self.assertLess(text.index("update-super"), text.index("flash vbmeta"))
        self.assertLess(text.index("flash vbmeta"), text.index("reboot fastboot"))


if __name__ == "__main__":
    unittest.main()
