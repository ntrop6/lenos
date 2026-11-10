"""Setup Wizard bootloader warning (Tier 2 #28).

The experimental implementation keeps the warning inside the existing welcome
page: no extra wizard action, no blocking. It is shown only when
``ro.boot.verifiedbootstate`` is not ``green``. The text deliberately warns
that re-locking an unsigned/modified build can make the device unbootable.
"""
from __future__ import annotations

import unittest

from harness import PATCH_ROOT, LenosPatchTest, patch_paths

PATCH = "0001-bootloader-unlocked-warning.patch"
ALIAS = "packages_apps_SetupWizard"
WELCOME = "app/src/main/java/org/lineageos/setupwizard/WelcomeActivity.kt"
LAYOUT = "app/src/main/res/layout/welcome_activity.xml"
STRINGS = "app/src/main/res/values/strings.xml"
COLORS = "app/src/main/res/values/colors.xml"
DRAWABLE = "app/src/main/res/drawable/bootloader_warning_background.xml"


class TestSetupWizardBootloaderWarning(LenosPatchTest):
    PROJECT = "packages/apps/SetupWizard"
    PATCHES = [PATCH]

    def test_patch_scope_is_the_welcome_page(self):
        patch = PATCH_ROOT / ALIAS / PATCH
        self.assertEqual(
            sorted(patch_paths(patch)),
            sorted([WELCOME, LAYOUT, STRINGS, COLORS, DRAWABLE]),
        )

    def test_warning_is_conditional_on_verified_boot_state(self):
        self.assert_contains(
            WELCOME,
            "import android.os.SystemProperties",
            'SystemProperties.get("ro.boot.verifiedbootstate", "green")',
            '!= "green"',
            "findViewById(R.id.bootloader_warning)",
            "bootloaderWarning.visibility = View.VISIBLE",
        )

    def test_warning_copy_does_not_encourage_relocking_blindly(self):
        self.assert_contains(
            STRINGS,
            "Bootloader is unlocked",
            "Verified boot is not protecting this device",
            "Do not lock the bootloader unless you are flashing a verified lenOS build",
            "can make the device unbootable",
        )

    def test_layout_has_a_hidden_warning_by_default(self):
        self.assert_contains(
            LAYOUT,
            'android:id="@+id/bootloader_warning"',
            'android:layout_marginBottom="16dp"',
            'android:visibility="gone"',
            'android:background="@drawable/bootloader_warning_background"',
        )

    def test_drawable_and_colors_exist(self):
        self.assert_contains(
            DRAWABLE,
            'android:shape="rectangle"',
            "@color/bootloader_warning_background",
            "@color/bootloader_warning_stroke",
        )
        self.assert_contains(
            COLORS,
            'name="bootloader_warning_background"',
            'name="bootloader_warning_text"',
            'name="bootloader_warning_stroke"',
        )

    def test_resources_are_well_formed(self):
        for rel in (LAYOUT, STRINGS, COLORS, DRAWABLE):
            self.assert_xml(rel)

    def test_kotlin_source_is_balanced(self):
        self.assert_balanced(WELCOME)


if __name__ == "__main__":
    unittest.main()
