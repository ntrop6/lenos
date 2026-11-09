"""Device-tree hardening configuration for the Nothing Phone (3a)/(3a) Pro.

Feature contract (see docs/features.md):
* Enterprise Wi-Fi without certificate validation cannot be configured from
  Settings/SetupWizard.
* Tethering does not advertise a device-identifying SSID.
* Default radio mode has no 2G (stingray/IMSI-catcher attack surface), and does
  not hard-disable any other RAT.
* The default device name (Bluetooth adapter / Wi-Fi Direct) is generic, not
  the commercial model.
* More profiles than stock are allowed (GrapheneOS parity: 32 full users).
* The lenOS product inherits the Lineage device config.
"""
from __future__ import annotations

import unittest

from harness import LenosPatchTest


class TestDeviceConfig(LenosPatchTest):
    PROJECT = "device/nothing/asteroids"
    PATCHES = [
        "0001-add-lenos-product.patch",
        "0002-wifi-privacy-hardening.patch",
        "0004-default-network-without-2g.patch",
        "0006-privacy-device-name.patch",
        "0007-multiuser-max-users.patch",
    ]
    PRODUCT = "lenos_asteroids.mk"
    WIFI = "rro_overlays/AsteroidsWifiOverlay/res/values/config.xml"
    PROPS = "system_ext.prop"
    DEVICE_NAME = "rro_overlays/AsteroidsSettingsProviderOverlay/res/values/defaults.xml"
    DEVICE_NAME_PRO = "rro_overlays/AsteroidsProSettingsProviderOverlay/res/values/defaults.xml"
    MULTIUSER = "rro_overlays/FrameworksResCommon_Vendor/res/values/config.xml"

    def test_xml_files_are_well_formed(self):
        self.assert_xml(self.WIFI)
        self.assert_xml(self.DEVICE_NAME)
        self.assert_xml(self.DEVICE_NAME_PRO)
        self.assert_xml(self.MULTIUSER)

    def test_lenos_product_inherits_lineage_and_vendor_config(self):
        self.assert_contains(
            self.PRODUCT,
            "$(call inherit-product, device/nothing/asteroids/lineage_asteroids.mk)",
            "$(call inherit-product, vendor/lenos/config/lenos.mk)",
            "PRODUCT_NAME := lenos_asteroids",
            "PRODUCT_DEVICE := asteroids",
        )

    def test_minimal_app_set_is_configured_before_inheriting(self):
        # LENOS_STRIP_PACKAGES/TARGET_EXCLUDES_AUDIOFX must be set in the
        # product makefile (before the inherit calls) to be visible to
        # vendor/lineage's app lists.
        body = self.text(self.PRODUCT)
        strip_at = body.index("LENOS_STRIP_PACKAGES :=")
        audiofx_at = body.index("TARGET_EXCLUDES_AUDIOFX := true")
        inherit_at = body.index("$(call inherit-product, device/nothing/asteroids/")
        self.assertLess(strip_at, inherit_at)
        self.assertLess(audiofx_at, inherit_at)
        # LineageOS 24.0 no longer ships Gallery2, so the default strip list is
        # empty; the hook must still be declared before the inheritance.
        self.assertIn("LENOS_STRIP_PACKAGES :=\n", body)

    def test_product_is_registered_for_lunch(self):
        self.assert_contains(
            "AndroidProducts.mk",
            "$(LOCAL_DIR)/lenos_asteroids.mk",
        )

    def test_product_does_not_change_the_build_fingerprint(self):
        # The explicit fingerprint override lives in the inherited device
        # makefile. lenOS must not add another assignment (a mention in a
        # comment is fine; the fingerprint is not preserved as attestation).
        body = self.text(self.PRODUCT)
        for needle in (
            "PRODUCT_BUILD_PROP_OVERRIDES +=",
            "PRODUCT_BUILD_PROP_OVERRIDES :=",
            "BUILD_FINGERPRINT=",
            "ro.product.name",
        ):
            self.assertNotIn(needle, body)

    def test_insecure_enterprise_wifi_is_disabled(self):
        self.assert_contains(
            self.WIFI,
            '<bool name="config_wifiAllowInsecureEnterpriseConfigurationsForSettingsAndSUW">false</bool>',
        )

    def test_tether_ssid_is_generic(self):
        self.assert_contains(
            self.WIFI,
            '<string translatable="false" name="wifi_tether_configure_ssid_default">AndroidAP</string>',
        )

    def test_default_network_mode_excludes_2g(self):
        # 28 = NR+LTE+WCDMA: no GSM/2G, WCDMA kept so roaming still works.
        self.assert_contains(self.PROPS, "ro.telephony.default_network=28,28")

    def test_default_device_name_is_generic(self):
        # The device name is what Bluetooth/Wi-Fi Direct neighbour devices see.
        for rel in (self.DEVICE_NAME, self.DEVICE_NAME_PRO):
            self.assert_contains(
                rel,
                '<string name="def_device_name">Android</string>',
                '<string name="def_device_name_simple">Android</string>',
            )
            self.assert_not_contains(rel, "Nothing Phone", "Phone (3a)")

    def test_more_profiles_are_allowed(self):
        # GrapheneOS parity: 32 full users instead of LineageOS's 4 (the
        # framework raw default is 1; this vendor overlay is what ships).
        self.assert_contains(
            self.MULTIUSER,
            '<integer name="config_multiuserMaximumUsers">32</integer>',
        )
        self.assert_not_contains(
            self.MULTIUSER,
            '<integer name="config_multiuserMaximumUsers">4</integer>',
        )


if __name__ == "__main__":
    unittest.main()
