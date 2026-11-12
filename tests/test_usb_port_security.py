"""USB data-line control (Tier 2 #22, stable).

The implementation uses Android's existing per-port ``enableUsbData`` HAL
operation instead of a vendor sysfs node. That makes it portable, but it also
means the policy is a no-op on USB HALs that do not implement the operation;
the Settings screen reports the unsupported state and the source-level tests
record the limitation.
"""
from __future__ import annotations

import unittest

from harness import VENDOR, LenosPatchTest, patch_paths

FWB_PATCH = "0030-lenos-usb-port-security.patch"
SETTINGS_PATCH = "0005-lenos-usb-port-security.patch"


class TestUsbPortSecurityFramework(LenosPatchTest):
    PROJECT = "frameworks/base"
    PATCHES = [FWB_PATCH]

    def test_patch_scope(self):
        patch = VENDOR / "patches" / "frameworks_base" / FWB_PATCH
        self.assertEqual(
            sorted(patch_paths(patch)),
            sorted([
                "core/java/android/hardware/usb/IUsbManager.aidl",
                "core/java/android/hardware/usb/UsbManager.java",
                "core/java/android/hardware/usb/UsbPortSecurity.java",
                "services/usb/java/com/android/server/usb/UsbPortSecurityController.java",
                "services/usb/java/com/android/server/usb/UsbService.java",
            ]),
        )

    def test_modes_and_persistent_key_are_grapheneos_compatible(self):
        self.assert_contains(
            "core/java/android/hardware/usb/UsbPortSecurity.java",
            "MODE_ALL_PORTS_DISABLED = 0",
            "MODE_CHARGING_ONLY = 1",
            "MODE_CHARGING_ONLY_WHEN_LOCKED = 2",
            "MODE_CHARGING_ONLY_WHEN_LOCKED_AFU = 3",
            "MODE_ALL_PORTS_ENABLED = 4",
            "MODE_SETTING = \"persist.security.usb_mode\"",
        )

    def test_data_is_blocked_while_locked_on_every_build(self):
        self.assert_contains(
            "core/java/android/hardware/usb/UsbPortSecurity.java",
            "DEFAULT_MODE = MODE_CHARGING_ONLY_WHEN_LOCKED",
            "public static final int DEFAULT_MODE = MODE_CHARGING_ONLY_WHEN_LOCKED;",
        )
        self.assert_not_contains(
            "core/java/android/hardware/usb/UsbPortSecurity.java",
            "Build.IS_DEBUGGABLE",
            "MODE_ALL_PORTS_ENABLED\n            : MODE_CHARGING_ONLY_WHEN_LOCKED",
        )

    def test_service_applies_policy_on_keyguard_changes(self):
        self.assert_contains(
            "services/usb/java/com/android/server/usb/UsbPortSecurityController.java",
            "mPortManager.getPorts()",
            "mPortManager.enableUsbData",
            "mKeyguardManager.isKeyguardLocked()",
            "mUnlockedSinceBoot",
            "MODE_CHARGING_ONLY_WHEN_LOCKED_AFU",
        )
        self.assert_contains(
            "services/usb/java/com/android/server/usb/UsbService.java",
            "mPortSecurity.onScreenLockChange(locked)",
            "mPortSecurity.systemReady()",
            "mPortSecurity.onUserUnlocked(user)",
            "getPortSecuritySetting",
            "updatePortSecuritySetting",
            "mPortSecurity.isBlockingData()",
        )
        self.assert_contains(
            "core/java/android/hardware/usb/IUsbManager.aidl",
            "getPortSecuritySetting()",
            "updatePortSecuritySetting(int newValue)",
        )

    def test_java_parses(self):
        for rel in (
                "core/java/android/hardware/usb/UsbPortSecurity.java",
                "services/usb/java/com/android/server/usb/UsbPortSecurityController.java",
                "core/java/android/hardware/usb/UsbManager.java",
                "services/usb/java/com/android/server/usb/UsbService.java"):
            self.assert_java_syntax(rel)


class TestUsbPortSecuritySettings(LenosPatchTest):
    PROJECT = "packages/apps/Settings"
    PATCHES = [SETTINGS_PATCH]

    def test_settings_screen_exposes_all_modes(self):
        self.assert_contains(
            "src/com/android/settings/security/UsbPortSecuritySettings.java",
            "UsbPortSecurity.MODE_ALL_PORTS_DISABLED",
            "UsbPortSecurity.MODE_CHARGING_ONLY",
            "UsbPortSecurity.MODE_CHARGING_ONLY_WHEN_LOCKED",
            "UsbPortSecurity.MODE_CHARGING_ONLY_WHEN_LOCKED_AFU",
            "UsbPortSecurity.MODE_ALL_PORTS_ENABLED",
            "updatePortSecuritySetting(value)",
            "usb_port_security_confirm_message",
            "getPorts().isEmpty()",
        )
        self.assert_contains(
            "res/xml/more_security_privacy_settings.xml",
            'android:key="usb_port_security"',
            'android:fragment="com.android.settings.security.UsbPortSecuritySettings"',
        )
        self.assert_contains(
            "res/values/strings.xml",
            'name="usb_port_security_title"',
            'name="usb_port_security_mode_when_locked"',
            'name="usb_port_security_confirm_message"',
        )

    def test_resources_and_java_parse(self):
        self.assert_xml("res/xml/more_security_privacy_settings.xml")
        self.assert_xml("res/values/strings.xml")
        self.assert_java_syntax(
            "src/com/android/settings/security/UsbPortSecuritySettings.java")


if __name__ == "__main__":
    unittest.main()
