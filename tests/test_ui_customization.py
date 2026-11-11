"""Local-only visual customization (LenosParts + SystemUI theme overlays).

Feature contract (see docs/axion-ui.md):

* The personalization layer is a local dashboard and preinstalled resource
  overlays. It has no INTERNET permission, no account, no telemetry and no
  Google/GMS/Play Integrity code path.
* Theme packs are mutable SystemUI overlays. LenosParts enables exactly one
  pack (or none) through OverlayManager.
* Motion presets only write the standard Android animation-scale settings.
* The stock LineageOS status bar panel remains the source of truth for clock,
  battery, network-traffic and brightness controls.
"""
from __future__ import annotations

import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from harness import VENDOR, java_syntax_errors

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"

THEMES = {
    "LenosThemeEmberSystemUI": "org.lenos.theme.ember.systemui",
    "LenosThemeMintSystemUI": "org.lenos.theme.mint.systemui",
    "LenosThemeMonoSystemUI": "org.lenos.theme.mono.systemui",
}

FRAMEWORK_THEMES = {
    "LenosThemeEmberFrameworks": "org.lenos.theme.ember.frameworks",
    "LenosThemeMintFrameworks": "org.lenos.theme.mint.frameworks",
    "LenosThemeMonoFrameworks": "org.lenos.theme.mono.frameworks",
}

QS_OVERLAYS = {
    "LenosQsColumns3": ("org.lenos.qs.columns3", "columns", 3),
    "LenosQsColumns5": ("org.lenos.qs.columns5", "columns", 5),
    "LenosQsRows3": ("org.lenos.qs.rows3", "rows", 3),
    "LenosQsRows5": ("org.lenos.qs.rows5", "rows", 5),
}

BANNED_JAVA = (
    "java.net.",
    "HttpURLConnection",
    "OkHttp",
    "new Socket",
    "Firebase",
    "com.google.android.gms",
    "PlayIntegrity",
    "TrickyStore",
    "axthemestore",
    "AxionParts",
)

BANNED_APP_TEXT = (
    "android.permission.INTERNET",
    "android.permission.ACCESS_NETWORK_STATE",
    "android.permission.ACCESS_WIFI_STATE",
    "android.permission.USE_BIOMETRIC",
    "com.google.android.gms",
    "firebase",
    "playintegrity",
    "trickystore",
    "axthemestore",
)


def parse_xml(rel: str) -> ET.Element:
    return ET.parse(VENDOR / rel).getroot()


class TestLenosPartsApp(unittest.TestCase):
    MANIFEST = "app/LenosParts/AndroidManifest.xml"

    def test_manifest_is_minimal_and_local(self):
        root = parse_xml(self.MANIFEST)
        permissions = {
            node.get(f"{ANDROID_NS}name")
            for node in root.findall("uses-permission")
        }
        self.assertEqual(
            permissions,
            {
                "android.permission.CHANGE_OVERLAY_PACKAGES",
                "android.permission.WRITE_SECURE_SETTINGS",
            },
            "LenosParts must keep its privileged permission set minimal",
        )
        for banned in BANNED_APP_TEXT:
            self.assertNotIn(banned.lower(),
                             (VENDOR / self.MANIFEST).read_text().lower())

        application = root.find("application")
        self.assertIsNotNone(application)
        self.assertEqual(
            application.get(f"{ANDROID_NS}allowBackup"), "false")
        activity = application.find("activity")
        self.assertIsNotNone(activity)
        self.assertEqual(activity.get(f"{ANDROID_NS}exported"), "true")
        actions = {
            node.get(f"{ANDROID_NS}name")
            for node in activity.findall("intent-filter/action")
        }
        self.assertIn("android.intent.action.MAIN", actions)

    def test_build_uses_platform_apis_and_no_network_dependency(self):
        body = (VENDOR / "app/LenosParts/Android.bp").read_text()
        self.assertIn('name: "LenosParts"', body)
        self.assertIn("platform_apis: true", body)
        self.assertIn("privileged: true", body)
        self.assertIn('certificate: "platform"', body)
        for banned in ("static_libs", "jni_libs", "sdk_version"):
            self.assertNotIn(banned, body)
        self.assertNotIn("INTERNET", body)

    def test_source_uses_local_overlays_and_settings_only(self):
        source = VENDOR / "app/LenosParts/src/org/lenos/parts/MainActivity.java"
        body = source.read_text()
        for needle in (
            "OverlayManager",
            "Process.myUserHandle()",
            "getOverlayInfosForTarget(",
            "installedPackages(",
            "systemUiInstalled.contains(",
            "org.lenos.theme.ember.systemui",
            "org.lenos.theme.mint.systemui",
            "org.lenos.theme.mono.systemui",
            "org.lenos.theme.ember.frameworks",
            "org.lenos.theme.mint.frameworks",
            "org.lenos.theme.mono.frameworks",
            "org.lenos.qs.columns3",
            "org.lenos.qs.columns5",
            "org.lenos.qs.rows3",
            "org.lenos.qs.rows5",
            "applyQsLayout(",
            "applyMonetSeed(",
            "restoreMonetSeed(",
            "backupMonetValue(",
            "Settings.Secure.THEME_CUSTOMIZATION_OVERLAY_PACKAGES",
            "android.theme.customization.system_palette",
            "android.theme.customization.theme_style",
            "android.theme.customization.color_source",
            "C96A1E",
            "2FA37C",
            "6B6F76",
            "VIBRANT",
            "TONAL_SPOT",
            "MONOCHROMATIC",
            "Settings.Global.ANIMATOR_DURATION_SCALE",
            "Settings.Global.TRANSITION_ANIMATION_SCALE",
            "Settings.Global.WINDOW_ANIMATION_SCALE",
            "org.lineageos.lineageparts.STATUS_BAR_SETTINGS",
        ):
            self.assertIn(needle, body)
        for banned in BANNED_JAVA:
            self.assertNotIn(banned, body)

    def test_java_parses(self):
        self.assertEqual(
            java_syntax_errors(
                VENDOR / "app/LenosParts/src/org/lenos/parts/MainActivity.java"),
            0,
        )


class TestMonetSeeding(unittest.TestCase):
    SOURCE = VENDOR / "app/LenosParts/src/org/lenos/parts/MainActivity.java"

    def test_seed_and_style_arrays_are_aligned(self):
        body = self.SOURCE.read_text()
        seeds_match = re.search(r"THEME_SEEDS = \{(.*?)\};", body, re.S)
        styles_match = re.search(r"THEME_STYLES = \{(.*?)\};", body, re.S)
        self.assertIsNotNone(seeds_match)
        self.assertIsNotNone(styles_match)
        seeds = re.findall(r'"([0-9A-F]{6})"', seeds_match.group(1))
        styles = re.findall(r'"([A-Z_]+)"', styles_match.group(1))
        self.assertEqual(seeds, ["C96A1E", "2FA37C", "6B6F76"])
        self.assertEqual(
            styles, ["VIBRANT", "TONAL_SPOT", "MONOCHROMATIC"])

    def test_stock_restores_only_values_the_app_wrote(self):
        body = self.SOURCE.read_text()
        self.assertIn("restoreMonetSeed(", body)
        self.assertIn("restoreMonetValue(", body)
        self.assertIn("owned.equals(current)", body,
                      "a user's later wallpaper/preset choice must survive")
        self.assertIn(
            "Settings.Secure.THEME_CUSTOMIZATION_OVERLAY_PACKAGES", body)
        self.assertIn('COLOR_SOURCE_PRESET = "preset"', body)


class TestThemeOverlays(unittest.TestCase):
    def test_overlays_are_mutable_systemui_packages(self):
        for name, package in THEMES.items():
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/AndroidManifest.xml")
                self.assertEqual(root.get("package"), package)
                node = root.find("overlay")
                self.assertIsNotNone(node)
                self.assertEqual(
                    node.get(f"{ANDROID_NS}targetPackage"),
                    "com.android.systemui",
                )
                self.assertEqual(
                    node.get(f"{ANDROID_NS}isStatic"), "false",
                    "theme packs must be user-toggleable, not static",
                )
                self.assertEqual(
                    root.find("application").get(f"{ANDROID_NS}hasCode"),
                    "false",
                )

                build = (VENDOR / f"rro/{name}/Android.bp").read_text()
                self.assertIn("runtime_resource_overlay", build)
                self.assertIn(f'name: "{name}"', build)
                self.assertIn("product_specific: true", build)
                self.assertIn('certificate: "platform"', build)
                self.assertNotIn("device_specific", build)

    def test_overlays_define_distinct_visual_values(self):
        radii = set()
        for name in THEMES:
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/res/values/theme.xml")
                values = {
                    node.get("name"): (node.text or "").strip()
                    for node in root
                }
                for resource in (
                    "notification_scrim_base",
                    "notification_legacy_background_color",
                    "status_bar_clock_color",
                    "qs_tile_divider",
                    "notification_corner_radius",
                    "qs_corner_radius",
                    "qs_tile_margin_horizontal",
                ):
                    self.assertIn(resource, values)
                radii.add(values["notification_corner_radius"])
        self.assertEqual(len(radii), len(THEMES),
                         "each pack must have a distinct corner radius")

    def test_no_network_or_remote_code_in_overlay_sources(self):
        for name in (*THEMES, *FRAMEWORK_THEMES, *QS_OVERLAYS):
            for path in (VENDOR / f"rro/{name}").rglob("*"):
                if not path.is_file():
                    continue
                body = path.read_text(encoding="utf-8", errors="replace")
                for banned in BANNED_APP_TEXT:
                    self.assertNotIn(banned.lower(), body.lower(),
                                     f"{path}: {banned}")


class TestFrameworkThemeOverlays(unittest.TestCase):
    KEY_ROLES = (
        "system_accent1_100_light",
        "system_accent1_100_dark",
        "system_accent1_500_light",
        "system_accent1_500_dark",
        "system_neutral1_500_light",
        "system_neutral1_500_dark",
        "system_primary_light",
        "system_primary_dark",
        "system_on_primary_light",
        "system_on_primary_dark",
        "system_surface_light",
        "system_surface_dark",
        "system_on_surface_light",
        "system_on_surface_dark",
    )

    def test_overlays_are_mutable_framework_packages(self):
        for name, package in FRAMEWORK_THEMES.items():
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/AndroidManifest.xml")
                self.assertEqual(root.get("package"), package)
                node = root.find("overlay")
                self.assertIsNotNone(node)
                self.assertEqual(
                    node.get(f"{ANDROID_NS}targetPackage"), "android")
                self.assertEqual(
                    node.get(f"{ANDROID_NS}isStatic"), "false",
                    "framework palettes must be user-toggleable",
                )
                self.assertEqual(
                    node.get(f"{ANDROID_NS}priority"), "1000",
                    "advisory only; the Monet seed is the reliable accent path",
                )
                self.assertEqual(
                    root.find("application").get(f"{ANDROID_NS}hasCode"),
                    "false",
                )

                build = (VENDOR / f"rro/{name}/Android.bp").read_text()
                self.assertIn("runtime_resource_overlay", build)
                self.assertIn(f'name: "{name}"', build)
                self.assertIn("product_specific: true", build)
                self.assertIn('certificate: "platform"', build)

    def test_palette_sets_are_complete_and_distinct(self):
        reference = None
        primary_tones = set()
        for name in FRAMEWORK_THEMES:
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/res/values/colors.xml")
                values = {
                    node.get("name"): (node.text or "").strip()
                    for node in root
                }
                self.assertEqual(len(values), 236,
                                 "every pack must define the same palette")
                for role in self.KEY_ROLES:
                    self.assertIn(role, values)
                for role, value in values.items():
                    self.assertRegex(
                        value, r"^#[0-9A-F]{8}$",
                        f"{name}: invalid color for {role}",
                    )
                if reference is None:
                    reference = set(values)
                else:
                    self.assertEqual(set(values), reference)
                primary_tones.add(values["system_primary_light"])
        self.assertEqual(
            len(primary_tones), len(FRAMEWORK_THEMES),
            "each pack must generate a distinct primary palette",
        )


class TestQuickSettingsOverlays(unittest.TestCase):
    def test_overlays_are_mutable_systemui_packages(self):
        for name, (package, kind, value) in QS_OVERLAYS.items():
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/AndroidManifest.xml")
                self.assertEqual(root.get("package"), package)
                node = root.find("overlay")
                self.assertIsNotNone(node)
                self.assertEqual(
                    node.get(f"{ANDROID_NS}targetPackage"),
                    "com.android.systemui",
                )
                self.assertEqual(
                    node.get(f"{ANDROID_NS}isStatic"), "false")
                self.assertEqual(
                    node.get(f"{ANDROID_NS}priority"), "200")
                self.assertEqual(
                    root.find("application").get(f"{ANDROID_NS}hasCode"),
                    "false",
                )

                build = (VENDOR / f"rro/{name}/Android.bp").read_text()
                self.assertIn("runtime_resource_overlay", build)
                self.assertIn(f'name: "{name}"', build)
                self.assertIn("product_specific: true", build)
                self.assertIn('certificate: "platform"', build)

    def test_overlays_override_the_expected_grid_resources(self):
        for name, (_, kind, value) in QS_OVERLAYS.items():
            with self.subTest(overlay=name):
                root = parse_xml(f"rro/{name}/res/values/config.xml")
                values = {
                    node.get("name"): int((node.text or "").strip())
                    for node in root
                }
                if kind == "columns":
                    self.assertEqual(
                        values,
                        {
                            "quick_settings_infinite_grid_num_columns": value,
                            "quick_settings_dual_shade_num_columns": value,
                            "quick_settings_split_shade_num_columns": value,
                        },
                    )
                else:
                    self.assertEqual(
                        values,
                        {"quick_settings_paginated_grid_num_rows": value},
                    )


class TestProductWiring(unittest.TestCase):
    def test_personalization_is_shipped(self):
        body = (VENDOR / "config/lenos.mk").read_text()
        for needle in ("LenosParts", *THEMES, *FRAMEWORK_THEMES,
                       *QS_OVERLAYS):
            self.assertIn(needle, body)

    def test_privapp_allowlist_is_scoped_to_the_app(self):
        root = parse_xml(
            "config/privapp-permissions-org.lenos.parts.xml")
        node = root.find("privapp-permissions")
        self.assertIsNotNone(node)
        self.assertEqual(node.get("package"), "org.lenos.parts")
        permissions = {
            child.get("name") for child in node.findall("permission")
        }
        self.assertEqual(
            permissions,
            {
                "android.permission.CHANGE_OVERLAY_PACKAGES",
                "android.permission.WRITE_SECURE_SETTINGS",
            },
        )

    def test_docs_describe_the_local_only_boundary(self):
        doc = (VENDOR / "docs/axion-ui.md").read_text()
        self.assertIn("local-only", doc.lower())
        self.assertIn("LenosParts", doc)
        self.assertIn("Theme Store", doc, "the excluded online store must be explicit")
        features = (VENDOR / "docs/features.md").read_text()
        self.assertIn("personalization", features.lower())


if __name__ == "__main__":
    unittest.main()
