"""Cellular null-cipher and unencrypted-connection defaults (stable).

Android exposes the controls through the radio HAL: null-cipher/integrity
enforcement requires network HAL 2.1, and cipher/integrity plus identifier
disclosure notifications require 2.2. lenOS turns the protections on by
default but only sends the requests when the HAL advertises the matching
version; otherwise the unsupported state is kept and the Settings toggles stay
hidden instead of crashing.
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest

TELEPHONY_PATCH = "0002-lenos-cellular-security-defaults.patch"


class TestCellularSecurityDefaults(LenosPatchTest):
    PROJECT = "frameworks/opt/telephony"
    PATCHES = [TELEPHONY_PATCH]

    def test_secure_preferences_are_the_defaults(self):
        self.assert_contains(
            "src/java/com/android/internal/telephony/Phone.java",
            "PREF_NULL_CIPHER_AND_INTEGRITY_ENABLED, false",
            "PREF_IDENTIFIER_DISCLOSURE_NOTIFICATIONS_ENABLED, true",
            "PREF_NULL_CIPHER_NOTIFICATIONS_ENABLED, true",
        )

    def test_hal_versions_gate_each_request(self):
        self.assert_contains(
            "src/java/com/android/internal/telephony/GsmCdmaPhone.java",
            "HAL_SERVICE_NETWORK",
            "RADIO_HAL_VERSION_2_1",
            "RADIO_HAL_VERSION_2_2",
            "isNetworkHalAtLeast",
            "handleNullCipherEnabledChange",
            "handleIdentifierDisclosureNotificationPreferenceChange",
            "handleNullCipherNotificationPreferenceChanged",
        )

    def test_unsupported_hal_degrades_without_crashing(self):
        self.assert_contains(
            "src/java/com/android/internal/telephony/GsmCdmaPhone.java",
            "mIsNullCipherAndIntegritySupported = false;",
            "mIsIdentifierDisclosureTransparencySupported = false;",
            "mIsNullCipherNotificationSupported = false;",
            "mIdentifierDisclosureNotifier.disable(mContext);",
            "mNullCipherNotifier.disable(mContext);",
        )
        self.assert_contains(
            "src/java/com/android/internal/telephony/GsmCdmaPhone.java",
            "doesResultIndicateModemSupport(ar)",
            "EVENT_SET_NULL_CIPHER_AND_INTEGRITY_DONE",
            "EVENT_SET_IDENTIFIER_DISCLOSURE_ENABLED_DONE",
            "EVENT_SET_SECURITY_ALGORITHMS_UPDATED_ENABLED_DONE",
        )

    def test_requests_only_run_when_the_hal_is_new_enough(self):
        self.assert_contains(
            "src/java/com/android/internal/telephony/GsmCdmaPhone.java",
            "mCi.setNullCipherAndIntegrityEnabled(",
            "mCi.setCellularIdentifierTransparencyEnabled(",
            "mCi.setSecurityAlgorithmsUpdatedEnabled(",
        )
        self.assert_not_contains(
            "src/java/com/android/internal/telephony/GsmCdmaPhone.java",
            "Qualcomm",
            "qti",
        )

    def test_java_parses(self):
        for rel in (
                "src/java/com/android/internal/telephony/Phone.java",
                "src/java/com/android/internal/telephony/GsmCdmaPhone.java"):
            self.assert_java_syntax(rel)


class TestCellularSecurityUnsupportedUi(LenosPatchTest):
    PROJECT = "packages/apps/Settings"
    EXTRA_FILES = [
        "src/com/android/settings/network/telephony/NullAlgorithmsPreferenceController.java",
        "src/com/android/settings/network/telephony/CellularSecurityNotificationsPreferenceController.java",
    ]

    def test_settings_hides_controls_for_unsupported_modems(self):
        self.assert_contains(
            "src/com/android/settings/network/telephony/NullAlgorithmsPreferenceController.java",
            "catch (UnsupportedOperationException e)",
            "return UNSUPPORTED_ON_DEVICE;",
            "isNullCipherAndIntegrityPreferenceEnabled()",
            "setNullCipherAndIntegrityEnabled(!isChecked)",
        )
        self.assert_contains(
            "src/com/android/settings/network/telephony/"
            "CellularSecurityNotificationsPreferenceController.java",
            "catch (UnsupportedOperationException e)",
            "return UNSUPPORTED_ON_DEVICE;",
            "isNullCipherNotificationsEnabled()",
            "isCellularIdentifierDisclosureNotificationsEnabled()",
        )

    def test_java_parses(self):
        self.assert_java_syntax(
            "src/com/android/settings/network/telephony/"
            "NullAlgorithmsPreferenceController.java")
        self.assert_java_syntax(
            "src/com/android/settings/network/telephony/"
            "CellularSecurityNotificationsPreferenceController.java")


if __name__ == "__main__":
    unittest.main()
