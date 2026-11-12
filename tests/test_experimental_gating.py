"""Build-time gate for the optional experimental lenOS work.

The experimental patches and OPSEC app live in this repository, but they are
not part of the default 1.0 build. This test locks down the three independent
gates:

* the stable patch root and the experimental patch root are separate;
* the driver only applies/installs experimental inputs when
  ``LENOS_EXPERIMENTAL=1``;
* the product makefile only inherits the experimental fragment under the same
  flag, and the default product does not name ``LenosOpsec``.

These are source-level checks. They do not build, boot, flash or validate any
experimental feature.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from harness import VENDOR

TOOL = VENDOR / "tools/lenos-patch.py"
STABLE = VENDOR / "patches"
EXPERIMENTAL = VENDOR / "patches-experimental"
EXPECTED_PROJECTS = {
    "bionic",
    "frameworks/base",
    "packages/apps/Settings",
    "packages/apps/SetupWizard",
    "packages/apps/Seedvault",
}


def series_entries(project_dir: Path) -> list[str]:
    return [line.strip() for line in (project_dir / "series").read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")]


class TestExperimentalLayout(unittest.TestCase):
    def test_patch_root_exists_and_has_no_stray_patches(self):
        self.assertTrue(EXPERIMENTAL.is_dir(), EXPERIMENTAL)
        actual_projects = set()
        for pdir in sorted(EXPERIMENTAL.iterdir()):
            if not pdir.is_dir():
                continue
            series = pdir / "series"
            self.assertTrue(series.is_file(), f"{pdir.name} has no series file")
            actual_projects.add(pdir.name)
            listed = set(series_entries(pdir))
            present = {p.name for p in pdir.glob("*.patch")}
            self.assertEqual(present - listed, set(),
                             f"{pdir.name}: patches not in series: {sorted(present - listed)}")
            self.assertEqual(listed - present, set(),
                             f"{pdir.name}: series lists missing patches: {sorted(listed - present)}")
        self.assertEqual(actual_projects, {p.replace("/", "_") for p in EXPECTED_PROJECTS})

    def test_no_duplicate_file_blocks_in_experimental_patches(self):
        # A duplicated new-file diff applies once but cannot be reversed: the
        # first reverse deletes the file and the second one fails. That breaks
        # reset/idempotence, so reject it at source level.
        for patch in EXPERIMENTAL.rglob("*.patch"):
            seen: dict[tuple[str, str], int] = {}
            for lineno, line in enumerate(
                    patch.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if not line.startswith("diff --git "):
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    key = (parts[2], parts[3])
                    seen[key] = seen.get(key, 0) + 1
            duplicates = {k: n for k, n in seen.items() if n > 1}
            self.assertEqual(duplicates, {}, f"{patch}: duplicate file blocks {duplicates}")

    def test_no_experimental_patch_in_the_stable_root(self):
        stable_files = {p.name for p in STABLE.rglob("*.patch")}
        for unexpected in (
                "0001-system-app-update-verity.patch",
                "0001-crash-log-viewer.patch",
                "0001-bootloader-unlocked-warning.patch",
                "0001-grapheneos-app-id-prefix.patch",
                "0001-hardened-thread-stacks.patch"):
            self.assertNotIn(unexpected, stable_files)

    def test_all_experimental_patches_apply_after_stable_context(self):
        # The one conflict found when stacking the series was ClipboardService's
        # import block: stable Secure Paste adds ApplicationInfo. Keep that
        # rebased context explicit so a future regeneration cannot silently
        # drop the stable-base requirement.
        patch = (EXPERIMENTAL / "frameworks_base"
                 / "0004-clipboard-clear-on-screen-off.patch")
        body = patch.read_text(encoding="utf-8")
        self.assertIn("+import android.content.IntentFilter;", body)
        self.assertIn(" import android.content.pm.ApplicationInfo;", body)

    def test_experimental_setup_wizard_and_seedvault_aliases_are_mapped(self):
        sys.path.insert(0, str(VENDOR / "tools"))
        from lenos_projects import alias_for  # noqa: PLC0415
        self.assertEqual(alias_for("packages/apps/SetupWizard"),
                         "packages_apps_SetupWizard")
        self.assertEqual(alias_for("packages/apps/Seedvault"),
                         "packages_apps_Seedvault")


class TestProductGate(unittest.TestCase):
    def test_opsec_app_does_not_pin_a_stale_target_sdk(self):
        manifest = (VENDOR / "experimental/app/LenosOpsec/AndroidManifest.xml").read_text(
            encoding="utf-8")
        self.assertNotIn("<uses-sdk", manifest)

    def test_default_product_does_not_name_experimental_packages(self):
        body = (VENDOR / "config/lenos.mk").read_text(encoding="utf-8")
        self.assertNotIn("LenosOpsec", body)
        # The fragment is guarded by the normalized build flag.
        self.assertIn(
            "ifneq ($(filter 1 true yes,$(LENOS_EXPERIMENTAL)),)", body)
        self.assertIn(
            "$(call inherit-product, vendor/lenos/config/lenos-experimental.mk)",
            body)

    def test_experimental_fragment_is_the_only_place_with_the_app(self):
        body = (VENDOR / "config/lenos-experimental.mk").read_text(encoding="utf-8")
        self.assertIn("LenosOpsec", body)
        self.assertIn("ro.lenos.experimental=1", body)
        self.assertNotIn("LenosOpsec", (VENDOR / "config/lenos.mk").read_text())

    def test_hardened_thread_stacks_are_part_of_the_experimental_series(self):
        fragment = (VENDOR / "config/lenos-experimental.mk").read_text()
        self.assertIn("ro.lenos.hardened_thread_stacks=1", fragment)
        # It is part of the experimental fragment, not a second build gate.
        self.assertNotIn("LENOS_HARDENED_THREAD_STACKS", fragment)
        # A stable/default build has neither the property nor the bionic gate.
        stable = (VENDOR / "config/lenos.mk").read_text()
        self.assertNotIn("ro.lenos.hardened_thread_stacks", stable)
        self.assertNotIn("LENOS_HARDENED_THREAD_STACKS", stable)

    def test_driver_reports_hardened_stacks_without_a_second_flag(self):
        body = (VENDOR / "lenos-1.0-shizuku.sh").read_text()
        self.assertNotIn("LENOS_HARDENED_THREAD_STACKS", body)
        for needle in (
                "__allocate_hardened_thread_mapping",
                "ro.lenos.hardened_thread_stacks=1",
                "hardened thread stacks"):
            self.assertIn(needle, body)

    def test_experimental_app_source_is_opt_in_and_local_only(self):
        app = VENDOR / "experimental/app/LenosOpsec"
        self.assertTrue((app / "Android.bp").is_file())
        manifest = (app / "AndroidManifest.xml").read_text()
        self.assertNotIn("android.permission.INTERNET", manifest)
        for rel in (app / "src/org/lenos/opsec").glob("*.java"):
            body = rel.read_text()
            self.assertNotIn("java.net.", body, rel)
            self.assertNotIn("HttpURLConnection", body, rel)
            self.assertNotIn("Socket", body, rel)

    def test_driver_gates_patch_application_and_app_install(self):
        body = (VENDOR / "lenos-1.0-shizuku.sh").read_text()
        for needle in (
                "experimental_enabled()",
                'export LENOS_EXPERIMENTAL="$experimental"',
                "--experimental --reset",
                "--experimental --check",
                "--experimental --apply",
                'cp -a "$VENDOR/experimental/app/." "$SRC/vendor/lenos/app/"',
                "experimental app present in a stable build tree"):
            self.assertIn(needle, body)

    def test_driver_detects_experimental_before_reset_and_validates_stable_first(self):
        body = (VENDOR / "lenos-1.0-shizuku.sh").read_text()
        detect = body.index('exp_status="$(python3 "$VENDOR/tools/lenos-patch.py"')
        wizard_reset = body.index('"$WIZARD" reset hardening')
        stable_gate = body.index('info "patchkit --require-applied"')
        exp_apply = body.index("--experimental --apply")
        self.assertLess(detect, wizard_reset,
                        "experimental state must be detected before the reset")
        self.assertLess(stable_gate, exp_apply,
                        "stable series must be validated before experimental apply")

    def test_driver_is_shell_syntax_clean(self):
        proc = subprocess.run(["bash", "-n", str(VENDOR / "lenos-1.0-shizuku.sh")],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class TestPatchToolModes(unittest.TestCase):
    def run_list(self, *args: str) -> list[str]:
        proc = subprocess.run([sys.executable, str(TOOL), "--list", *args],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [line for line in proc.stdout.splitlines() if line.strip()]

    def test_experimental_list_has_only_opt_in_projects(self):
        lines = self.run_list("--experimental")
        projects = {line.split("\t", 1)[0] for line in lines}
        self.assertEqual(projects, EXPECTED_PROJECTS)
        self.assertEqual(len(lines), 11)
        self.assertIn("bionic\t0001-hardened-thread-stacks.patch", lines)
        self.assertIn("frameworks/base\t0001-system-app-update-verity.patch", lines)
        self.assertIn("packages/apps/Settings\t0005-native-debugging-block.patch", lines)
        self.assertFalse(any("usb-port-security" in line for line in lines))
        self.assertFalse(any(line.startswith("vendor/lenos\t") for line in lines))

    def test_stable_list_does_not_include_experimental_projects(self):
        projects = {line.split("\t", 1)[0] for line in self.run_list()}
        self.assertNotIn("packages/apps/SetupWizard", projects)
        self.assertNotIn("packages/apps/Seedvault", projects)

    def test_experimental_app_is_present_as_source_not_a_patch(self):
        self.assertTrue((VENDOR / "experimental/app/LenosOpsec/Android.bp").is_file())
        self.assertFalse((EXPERIMENTAL / "vendor_lenos").exists())


if __name__ == "__main__":
    unittest.main()
