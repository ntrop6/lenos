"""lenOS product configuration (vendor/lenos itself, no upstream patches).

Feature contract (see docs/features.md):
* The product ships a minimal app set plus the lenOS security companion app.
* Privacy-critical resource defaults live in static RROs, not in patched
  upstream files: framework-res NTP fallback, SettingsProvider first-boot
  defaults, NetworkStack connectivity-check endpoints.
* No Google infrastructure is referenced by any lenOS-shipped resource.
* The security app is built against the platform API surface with an explicit,
  least-privilege permission allowlist. Wi-Fi privacy defaults are
  GrapheneOS-faithful per-network defaults (packages/modules/Wifi patch), so
  the app needs no Wi-Fi permissions and carries no global hostname switch.
"""
from __future__ import annotations

import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from harness import VENDOR, java_syntax_errors

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"

RROS = {
    "LenosFrameworksOverlay": "android",
    "LenosSettingsProviderOverlay": "com.android.providers.settings",
    "LenosNetworkStackOverlay": "com.android.networkstack",
}


def strip_xml_comments(body: str) -> str:
    return re.sub(r"<!--.*?-->", "", body, flags=re.S)


def strip_bp_comments(body: str) -> str:
    return re.sub(r"(?m)^\s*//.*$", "", body)


def make_logical_statements(body: str) -> list[str]:
    """Join backslash-continued lines the way GNU make does.

    A comment line without a trailing backslash ends the logical statement.
    That is exactly the failure mode this parser is meant to catch.
    """
    statements: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        current.append(line)
        if not line.rstrip().endswith("\\"):
            statements.append("\n".join(current))
            current = []
    if current:
        statements.append("\n".join(current))
    return statements


def product_property_tokens(body: str) -> set[str]:
    tokens: set[str] = set()
    for statement in make_logical_statements(body):
        head = statement.lstrip()
        if not head.startswith("PRODUCT_PRODUCT_PROPERTIES"):
            continue
        joined = re.sub(r"\\\s*\n", " ", statement)
        joined = re.sub(r"(?m)#.*$", "", joined)
        joined = re.sub(
            r"^\s*PRODUCT_PRODUCT_PROPERTIES\s*(\+=|:=|\?=|=)", "", joined
        )
        for token in joined.split():
            if "=" in token:
                tokens.add(token)
    return tokens


class ProductConfigTestCase(unittest.TestCase):
    def text(self, rel: str) -> str:
        path = VENDOR / rel
        self.assertTrue(path.is_file(), f"missing file: {rel}")
        return path.read_text(encoding="utf-8")


class TestProductMakefile(ProductConfigTestCase):
    MK = "config/lenos.mk"

    def test_ships_the_security_app_and_the_three_overlays(self):
        self.assertIn("LenosSecurity", self.text(self.MK))
        for overlay in RROS:
            self.assertIn(overlay, self.text(self.MK))

    def test_product_properties_are_privacy_hardening(self):
        body = self.text(self.MK)
        properties = product_property_tokens(body)
        for needle in (
            "ro.lenos.version=1.0.0",
            "ro.lenos.base=lineage-24.0",
            "ro.lenos.dns=dns.quad9.net",
            "ro.lenos.security.auto_bfu=init",
            "ro.lenos.security.duress=framework",
            "persist.traced.enable=0",
            "persist.logd.size.radio=64K",
            "persist.vendor.verbose_logging_enabled=0",
            "persist.vendor.radio.adb_log_on=0",
            "persist.vendor.radio.ims_log_enabled=0",
            "persist.vendor.sys.modem.logging.enable=0",
            "persist.vendor.radio.snapshot_enabled=0",
            "persist.vendor.radio.snapshot_timer=0",
        ):
            self.assertIn(
                needle,
                properties,
                f"{needle} is not in a continued PRODUCT_PRODUCT_PROPERTIES "
                "statement; check for a comment line without a trailing "
                "backslash inside the list",
            )

    def test_comments_do_not_break_property_continuations(self):
        body = self.text(self.MK)
        for statement in make_logical_statements(body):
            lines = statement.splitlines()
            for index, line in enumerate(lines[:-1]):
                if line.lstrip().startswith("#"):
                    self.fail(
                        "comment line inside a backslash continuation at "
                        f"{index + 1}: {line!r}"
                    )

    def test_no_removed_build_variables_or_legacy_props(self):
        body = self.text(self.MK)
        # PRODUCT_PACKAGES_REMOVE does not exist in Lineage 24.0 build/make;
        # app removal is done where the app lists are declared.
        self.assertNotIn("PRODUCT_PACKAGES_REMOVE", body)
        # net.hostname is dead in the modern network stack and must not come
        # back through the product props.
        self.assertNotIn("net.hostname", body)
        # ExactCalculator is already part of the Lineage common app set.
        self.assertNotIn("ExactCalculator", body)

    def test_compressed_apex_is_disabled(self):
        # GrapheneOS parity. updatable_apex.mk is inherited earlier, through
        # lineage_asteroids.mk -> full_base_telephony.mk -> generic_system.mk,
        # and sets PRODUCT_COMPRESSED_APEX := true; lenos.mk is inherited
        # afterwards, so the last (this) assignment wins.
        body = self.text(self.MK)
        self.assertEqual(
            len(re.findall(r"(?m)^PRODUCT_COMPRESSED_APEX := false$", body)), 1)
        # And no other assignment that could win later (comments mention the
        # upstream "true" default, so anchor to line starts).
        self.assertEqual(
            len(re.findall(r"(?m)^PRODUCT_COMPRESSED_APEX\s*:?=", body)), 1)

    def test_build_time_overlay_approach_is_gone(self):
        # Replaced by input RROs: PRODUCT_ENFORCE_RRO_TARGETS := * in the
        # device tree converts product overlays to RROs anyway, and the RROs
        # are explicit about target packages and priority.
        self.assertFalse((VENDOR / "overlay").exists(),
                         "vendor/lenos/overlay must not exist anymore")


class TestRuntimeOverlays(ProductConfigTestCase):
    def test_all_shipped_xml_parses(self):
        # XML comments may not contain "--"; aapt2/Expat reject the whole
        # file. This catches separator comments such as
        # "<!-- Radios ---- -->" before the build does.
        parsed = 0
        for root_dir in (
            VENDOR / "config",
            VENDOR / "rro",
            VENDOR / "app",
            VENDOR / "experimental",
        ):
            for path in sorted(root_dir.rglob("*.xml")):
                with self.subTest(path=str(path.relative_to(VENDOR))):
                    ET.parse(path)
                    parsed += 1
        self.assertGreater(parsed, 0)

    def test_androidbp_declares_static_product_overlays(self):
        for overlay in RROS:
            body = self.text(f"rro/{overlay}/Android.bp")
            self.assertIn("runtime_resource_overlay", body)
            self.assertIn(f'name: "{overlay}"', body)
            self.assertIn("product_specific: true", body)
            # Soong rejects device_specific together with product_specific.
            self.assertNotIn("device_specific", body)

    def test_manifests_are_static_and_target_the_right_package(self):
        for overlay, target in RROS.items():
            rel = f"rro/{overlay}/AndroidManifest.xml"
            root = ET.parse(VENDOR / rel).getroot()
            self.assertEqual(root.tag, "manifest", rel)
            self.assertTrue(root.get("package"), rel)
            node = root.find("overlay")
            self.assertIsNotNone(node, rel)
            self.assertEqual(node.get(f"{ANDROID_NS}targetPackage"), target, rel)
            self.assertEqual(node.get(f"{ANDROID_NS}isStatic"), "true", rel)
            application = root.find("application")
            self.assertIsNotNone(application, f"{rel}: hasCode declaration missing")
            self.assertEqual(application.get(f"{ANDROID_NS}hasCode"), "false", rel)

    def test_only_networkstack_uses_a_target_name(self):
        # NetworkStack is the only target here that declares an <overlayable>.
        for overlay, _ in RROS.items():
            root = ET.parse(VENDOR / f"rro/{overlay}/AndroidManifest.xml").getroot()
            node = root.find("overlay")
            target_name = node.get(f"{ANDROID_NS}targetName")
            if overlay == "LenosNetworkStackOverlay":
                self.assertEqual(target_name, "NetworkStackConfig")
            else:
                self.assertIsNone(target_name, f"{overlay} must not set targetName")

    def test_networkstack_checks_use_cloudflare_only(self):
        body = strip_xml_comments(
            self.text("rro/LenosNetworkStackOverlay/res/values/config.xml"))
        self.assertIn("http://cp.cloudflare.com/generate_204", body)
        self.assertIn("https://cp.cloudflare.com/generate_204", body)
        for banned in ("gstatic", "google", "connectivitycheck."):
            self.assertNotIn(banned, body)

    def test_frameworks_ntp_fallback_is_not_google(self):
        body = strip_xml_comments(
            self.text("rro/LenosFrameworksOverlay/res/values/config.xml"))
        self.assertIn("ntp://pool.ntp.org", body)
        for banned in ("google", "android.com", "grapheneos"):
            self.assertNotIn(banned, body)

    def test_settings_defaults_are_hardened_and_do_not_overlap_device_rros(self):
        body = self.text("rro/LenosSettingsProviderOverlay/res/values/defaults.xml")
        for needle in (
            '<string name="def_lenos_private_dns_mode" translatable="false">hostname</string>',
            '<string name="def_lenos_private_dns_specifier" translatable="false">dns.quad9.net</string>',
            '<string name="def_lenos_ntp_server" translatable="false">pool.ntp.org</string>',
            '<bool name="def_bluetooth_on">false</bool>',
            '<bool name="def_wifi_wakeup_enabled">false</bool>',
            '<bool name="def_networks_available_notification_on">false</bool>',
            '<integer name="def_location_mode">0</integer>',
            '<bool name="def_usb_mass_storage_enabled">false</bool>',
            '<bool name="def_lock_screen_show_qr_code_scanner">false</bool>',
        ):
            self.assertIn(needle, body)
        # Wi-Fi privacy defaults are carried by the Wi-Fi module patch
        # (packages_modules_Wifi/0001) since the GrapheneOS-fidelity redo; the
        # RRO must not define a competing value.
        self.assertNotIn("def_lenos_wifi_force_non_persistent_mac_randomization", body)
        # def_device_name is owned by the device RROs (patched by
        # device_nothing_asteroids/0006-privacy-device-name.patch); defining
        # it here as well would create two competing static overlays.
        self.assertNotIn("def_device_name", body)


class TestSecurityApp(ProductConfigTestCase):
    APP = "app/LenosSecurity"

    def test_built_against_the_platform_api_surface(self):
        body = strip_bp_comments(self.text(f"{self.APP}/Android.bp"))
        self.assertIn("platform_apis: true", body)
        self.assertNotRegex(body, r"^\s*sdk_version\s*:", "sdk_version must not be set")

    def test_holds_only_needed_privileged_permissions(self):
        # The GrapheneOS-faithful Wi-Fi redo removed the app's only
        # NETWORK_SETTINGS consumer (the global hostname clamp) and the only
        # Settings.System writer (the old Lineage scramble key); neither
        # permission may linger in the manifest or the allowlist.
        manifest = self.text(f"{self.APP}/AndroidManifest.xml")
        allowlist = self.text("config/privapp-permissions-org.lenos.security.xml")
        for perm in ("android.permission.NETWORK_SETTINGS",
                     'android.permission.WRITE_SETTINGS"'):
            self.assertNotIn(perm, manifest)
            self.assertNotIn(perm, allowlist)
        for perm in ("android.permission.ACCESS_KEYGUARD_SECURE_STORAGE",
                     "android.permission.WRITE_SECURE_SETTINGS",
                     "android.permission.READ_PRIVILEGED_PHONE_STATE"):
            self.assertIn(perm, manifest)
            self.assertIn(perm, allowlist)

    def test_version_strings_are_1_0_0(self):
        manifest = self.text(f"{self.APP}/AndroidManifest.xml")
        self.assertIn('android:versionName="1.0.0"', manifest)
        strings = self.text(f"{self.APP}/res/values/strings.xml")
        self.assertIn('<string name="lenos_version">1.0.0</string>', strings)
        self.assertNotIn("shizuku", strings.lower())

    def test_no_global_wifi_hostname_switch(self):
        # The control is per network in Wi-Fi settings now; the app must not
        # keep a lying toggle for the removed global clamp API.
        main = self.text(f"{self.APP}/src/org/lenos/security/MainActivity.java")
        self.assertNotIn("setSendDhcpHostnameRestriction", main)
        self.assertNotIn("lenos_wifi_send_dhcp_hostname_restriction", main)
        self.assertIn("requests carry no hostname", main)

    def test_scramble_switch_uses_the_secure_key(self):
        main = self.text(f"{self.APP}/src/org/lenos/security/MainActivity.java")
        self.assertIn('SCRAMBLE_KEY = "lockscreen_scramble_pin_layout"', main)
        self.assertIn("Settings.Secure.putInt(getContentResolver(), SCRAMBLE_KEY, value)", main)
        # The app is platform-signed and privileged; no su/app_process fallback.
        self.assertNotIn("settingsPutSecure", main)
        self.assertNotIn("RootShell", main)

    def test_main_activity_still_parses(self):
        self.assertEqual(
            java_syntax_errors(
                VENDOR / f"{self.APP}/src/org/lenos/security/MainActivity.java"),
            0)


if __name__ == "__main__":
    unittest.main()
