"""GrapheneOS: status-bar location privacy indicator (Tier 2 #16).

LineageOS 24.0 (Android 17) contains the SystemUI location-indicator
machinery, and AOSP's ``cp1a`` release config (inherited by the ``cp2a``
config LineageOS selects) already enables
``android.location.flags.location_indicators_enabled``. Stock LineageOS 24.0
therefore shows the indicator for fine location; GrapheneOS additionally
makes it cover *all* location access, not just apps that hold the fine-location
op.

The port is the code patch only:
``patches/frameworks_base/0027-lenos-location-indicator.patch`` —
``AppOpsPrivacyItemMonitor`` now watches ``OP_COARSE_LOCATION`` as well as
``OP_FINE_LOCATION`` (subscription, item mapping and two filters), matching
GrapheneOS, so coarse-only apps light the indicator too. System apps and
background accesses keep GrapheneOS's non-display accounting behaviour.

The A16-era lenOS release-config override (``vendor/lenos/release/``) is not
needed on Android 17 and was dropped during the port.

Not ported: GrapheneOS's accumulated location-usage logger
(``LocationAccumulatedLogger``; A17 ships a dumpsys-only version) and the
indicator animation/outline flags.
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest, VENDOR


class TestLocationIndicatorPatch(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = ["0027-lenos-location-indicator.patch"]

    MONITOR = ("packages/SystemUI/src/com/android/systemui/privacy/"
               "AppOpsPrivacyItemMonitor.kt")

    def test_location_op_subscription_includes_coarse(self):
        self.assert_contains(
            self.MONITOR,
            "val OPS_LOCATION =\n"
            "            intArrayOf(AppOpsManager.OP_FINE_LOCATION, "
            "AppOpsManager.OP_COARSE_LOCATION)")

    def test_no_fine_only_filters_remain(self):
        self.assert_not_contains(
            self.MONITOR,
            "item.code == AppOpsManager.OP_FINE_LOCATION",
            "appOpItem.code == AppOpsManager.OP_FINE_LOCATION",
            "OP_FINE_LOCATION -> PrivacyType.TYPE_LOCATION")

    def test_location_state_tracking_uses_both_ops(self):
        self.assert_contains(
            self.MONITOR,
            ".filter { item -> item.code in OPS_LOCATION }",
            "if (item.code in OPS_LOCATION) {")

    def test_coarse_maps_to_location_privacy_type(self):
        self.assert_contains(
            self.MONITOR,
            "AppOpsManager.OP_FINE_LOCATION,\n"
            "                AppOpsManager.OP_COARSE_LOCATION -> "
            "PrivacyType.TYPE_LOCATION")

    def test_mic_camera_ops_untouched(self):
        self.assert_contains(
            self.MONITOR,
            "AppOpsManager.OP_CAMERA,",
            "AppOpsManager.OP_PHONE_CALL_CAMERA,",
            "AppOpsManager.OP_RECORD_AUDIO,",
            "AppOpsManager.OP_RECEIVE_SANDBOX_TRIGGER_AUDIO,")

    def test_patch_is_in_the_series(self):
        series = (VENDOR / "patches/frameworks_base/series").read_text()
        self.assertIn("0027-lenos-location-indicator.patch", series)

    def test_balanced(self):
        self.assert_balanced(self.MONITOR)


if __name__ == "__main__":
    unittest.main()
