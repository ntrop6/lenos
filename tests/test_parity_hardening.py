"""GrapheneOS parity hardening tweaks (frameworks/base, see docs/features.md).

Small line-level ports from GrapheneOS that close specific gaps:

* ``0012`` flips the seeded default of ``LOCK_SCREEN_ALLOW_PRIVATE_NOTIFICATIONS``
  to ``false``: lockscreen notifications hide their content until the user
  explicitly allows it (new installs/users only; upgraded devices keep the
  stored value).
* ``0011`` PendingIntent immutability warp: apps that forget to pass
  FLAG_IMMUTABLE/FLAG_MUTABLE no longer crash with IllegalArgumentException
  once the S+ compat change is enforced; the framework logs and forces
  FLAG_IMMUTABLE, and all four creation paths honour the returned flags.
  Passing both flags still throws.
* ``0010`` tightens the system-clock paranoia threshold from 2 s to 250 ms so
  unexpected clock changes are logged sooner.
* ``0009`` raises the maximum password length to GrapheneOS's value of 128
  (was 64). The fingerprint lockout threshold is not changed: the device uses
  an AIDL fingerprint HAL, where lockout is owned by the vendor HAL, and the
  framework's ``LockoutFrameworkImpl`` only applies to HIDL sensors.
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest, VENDOR


class TestCredentialHardening(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = ["0009-lenos-credential-hardening.patch"]
    DPM = "core/java/android/app/admin/DevicePolicyManager.java"

    def test_patch_does_not_touch_the_hidl_only_lockout_tracker(self):
        # asteroids uses an AIDL fingerprint HAL. LockoutFrameworkImpl is only
        # attached by the HIDL adapter, so changing it would be a no-op here.
        patch = (VENDOR / "patches/frameworks_base/0009-lenos-credential-hardening.patch")
        body = patch.read_text(encoding="utf-8")
        self.assertNotIn("LockoutFrameworkImpl.java", body)
        self.assertNotIn("MAX_FAILED_ATTEMPTS_LOCKOUT_PERMANENT", body)

    def test_maximum_password_length_is_128(self):
        self.assert_contains(
            self.DPM,
            "public static final int MAX_PASSWORD_LENGTH = 128;",
        )
        self.assert_not_contains(
            self.DPM,
            "public static final int MAX_PASSWORD_LENGTH = 64;",
        )
        self.assert_java_syntax(self.DPM)


class TestClockDriftWarning(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = ["0010-lenos-clock-drift-warning.patch"]
    SRC = ("services/core/java/com/android/server/timedetector/"
           "TimeDetectorStrategyImpl.java")

    def test_threshold_matches_grapheneos(self):
        self.assert_contains(
            self.SRC,
            "SYSTEM_CLOCK_PARANOIA_THRESHOLD_MILLIS = 250;",
        )
        self.assert_not_contains(
            self.SRC,
            "SYSTEM_CLOCK_PARANOIA_THRESHOLD_MILLIS = 2 * 1000;",
        )
        self.assert_java_syntax(self.SRC)


class TestPendingIntentImmutable(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = ["0011-lenos-pendingintent-immutable.patch"]
    SRC = "core/java/android/app/PendingIntent.java"

    def test_missing_mutability_logs_and_forces_immutable(self):
        self.assert_contains(
            self.SRC,
            "private static int checkPendingIntent2(",
            "Log.e(TAG, msg);",
            "return flags | PendingIntent.FLAG_IMMUTABLE;",
            "return flags;",
        )

    def test_all_creation_paths_use_the_returned_flags(self):
        body = self.text(self.SRC)
        self.assertEqual(
            body.count("flags = checkPendingIntent2(flags, intent, context"),
            3,
            "the three single-intent creation paths must assign the flags back")
        self.assert_contains(
            self.SRC,
            "flags = checkPendingIntent2(flags, intents[i], context",
        )
        self.assert_not_contains(self.SRC, "checkPendingIntent(flags")

    def test_syntax(self):
        self.assert_java_syntax(self.SRC)


class TestLockscreenNotificationPrivacy(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = ["0012-lenos-lockscreen-notification-privacy.patch"]
    SRC = "packages/SettingsProvider/res/values/defaults.xml"

    def test_private_notifications_hidden_by_default(self):
        self.assert_contains(
            self.SRC,
            '<bool name="def_lock_screen_allow_private_notifications">false</bool>',
        )
        self.assert_not_contains(
            self.SRC,
            '<bool name="def_lock_screen_allow_private_notifications">true</bool>',
        )

    def test_xml_is_well_formed(self):
        self.assert_xml(self.SRC)


if __name__ == "__main__":
    unittest.main()
