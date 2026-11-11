"""Strip-package hook (vendor/lineage product config).

Feature contract (see docs/features.md):
* ``LENOS_STRIP_PACKAGES`` lets the product makefile drop bundled apps.
* The lenOS product strips Updater, Jelly, Etar, Twelve, Recorder and
  Glimpse; AudioFX uses LineageOS' existing TARGET_EXCLUDES_AUDIOFX switch.
* Dropping is done by filtering the app lists where they are declared, so the
  mechanism works with the build system's product-inheritance model (product
  makefiles cannot filter inherited PRODUCT_PACKAGES values).
* Nothing else about the LineageOS configuration changes.
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest


class TestAppSet(LenosPatchTest):
    PROJECT = "vendor/lineage"
    PATCHES = ["0001-lenos-strip-packages.patch"]
    COMMON = "config/common.mk"
    MOBILE = "config/common_mobile.mk"
    FULL = "config/common_mobile_full.mk"

    def test_filter_is_applied_where_apps_are_declared(self):
        self.assert_contains(
            self.COMMON,
            "PRODUCT_PACKAGES += $(filter-out $(LENOS_STRIP_PACKAGES), \\",
            "ExactCalculator \\",
            "Jelly)",
        )
        self.assert_contains(
            self.MOBILE,
            "PRODUCT_PACKAGES += $(filter-out $(LENOS_STRIP_PACKAGES), \\",
            "AvatarPicker \\",
            "LatinIME)",
        )
        self.assert_contains(
            self.FULL,
            "PRODUCT_PACKAGES += $(filter-out $(LENOS_STRIP_PACKAGES), \\",
            "Camelot \\",
            "Twelve)",
        )

    def test_updater_is_filtered_and_its_init_script_is_guarded(self):
        self.assert_contains(
            self.COMMON,
            "LineageSettingsProvider \\",
            "Updater)",
            "ifeq ($(filter Updater,$(LENOS_STRIP_PACKAGES)),)",
            "endif",
        )
        # A stripped Updater must not leave an ownerless init.rc copy behind.
        body = self.text(self.COMMON)
        copy_at = body.index("init.lineage-updater.rc:")
        guard_at = body.index(
            "ifeq ($(filter Updater,$(LENOS_STRIP_PACKAGES)),)")
        self.assertLess(guard_at, copy_at)

    def test_app_names_are_preserved_for_products_that_keep_them(self):
        # The filter must not delete the names, only skip them at build time:
        # stock LineageOS app selection stays available.
        for rel in (self.COMMON, self.MOBILE, self.FULL):
            body = self.text(rel)
            self.assertNotIn("$(filter-out $(LENOS_STRIP_PACKAGES),)", body)

    def test_make_syntax_stays_balanced(self):
        for rel in (self.COMMON, self.MOBILE, self.FULL):
            self.assert_balanced(rel)

    def test_no_unrelated_config_changes(self):
        # The patch must only touch the three app lists.
        for rel in (self.COMMON, self.MOBILE, self.FULL):
            body = self.text(rel)
            self.assertNotIn("PRODUCT_SIZE :=", body.replace("PRODUCT_SIZE := full", ""))
            self.assertIn("PRODUCT_PACKAGES", body)


if __name__ == "__main__":
    unittest.main()
